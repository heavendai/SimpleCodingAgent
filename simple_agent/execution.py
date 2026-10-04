"""Execution is a host-selected dependency, never a model-selected permission.

V01-V10 deliberately use TrustedHostExecutor for our known fixture only.
V11 requires Linux Bubblewrap; setup failure never selects TrustedHostExecutor.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Protocol


class SandboxUnavailable(RuntimeError):
    """No repository code may run after this failure."""


class Executor(Protocol):
    name: str

    def run_tests(self, root: Path) -> dict: ...


class TrustedHostExecutor:
    """Compatibility lesson backend. NOT a sandbox, even with a fixed command."""
    name = "trusted-host"

    def run_tests(self, root):
        command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR"}}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            done = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                  text=True, timeout=5, check=False)
            result = {"ok": True, "passed": done.returncode == 0,
                      "exit_code": done.returncode, "output": (done.stdout + done.stderr)[-6000:]}
        except subprocess.TimeoutExpired:
            result = {"ok": True, "passed": False, "exit_code": None,
                      "output": "Test execution exceeded 5 seconds"}
        return result | {"command": "python -B -m unittest discover -s tests -v",
                         "execution": {"backend": self.name, "isolated": False}}


@dataclass(frozen=True)
class SandboxLimits:
    wall_seconds: float = 5.0
    cpu_seconds: int = 3
    address_space_bytes: int = 256 * 1024 * 1024
    file_bytes: int = 1024 * 1024
    open_files: int = 64
    processes: int = 64
    output_bytes: int = 64 * 1024
    scratch_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
            if name != "wall_seconds" and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")


# A fixed, host-owned manifest, not arbitrary repository discovery. Never mount
# the original repository, its .env/.git, credentials, sockets, or checkpoint.
TEST_INPUTS = ("stats.py", "tests/test_stats.py")
MAX_INPUT_BYTES = 64 * 1024
TEST_PROGRAM = (
    "import sys,unittest; sys.path.insert(0,'/workspace'); "
    "suite=unittest.defaultTestLoader.discover('/workspace/tests'); "
    "result=unittest.TextTestRunner(verbosity=2).run(suite); "
    "sys.exit(not result.wasSuccessful())"
)
PROBE_PROGRAM = (
    "import json,os,sys; "
    "print(json.dumps({'python':sys.version.split()[0],"
    "'net':os.readlink('/proc/self/ns/net'), 'pid':os.readlink('/proc/self/ns/pid'),"
    "'status':open('/proc/self/status').read()}))"
)


def stage_inputs(root: Path, destination: Path):
    """Open every component without following symlinks (Linux dir_fd API)."""
    hashes = {}
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise SandboxUnavailable(f"Cannot open snapshot root: {error}") from error
    try:
        for name in TEST_INPUTS:
            parent = os.dup(root_fd)
            try:
                parts = Path(name).parts
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    os.close(parent)
                    parent = child
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                with os.fdopen(fd, "rb") as source:
                    metadata = os.fstat(source.fileno())
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_INPUT_BYTES:
                        raise SandboxUnavailable(f"Sandbox input must be a regular file <=64 KiB: {name}")
                    data = source.read(MAX_INPUT_BYTES + 1)
                    if len(data) > MAX_INPUT_BYTES:
                        raise SandboxUnavailable(f"Sandbox input grew beyond 64 KiB: {name}")
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                hashes[name] = hashlib.sha256(data).hexdigest()
            finally:
                os.close(parent)
    except OSError as error:
        raise SandboxUnavailable(f"Cannot create safe input snapshot: {error}") from error
    finally:
        os.close(root_fd)
    return hashes


def collect_bounded(command, *, limits, pass_fds=()):
    """No shell; cap bytes while reading, rather than after capture_output."""
    started = time.monotonic()
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, cwd="/", env={}, close_fds=True,
                             pass_fds=pass_fds, start_new_session=True)
    output = bytearray()
    stopped = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = limits.wall_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    stopped = "wall_timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.05)):
                    chunk = os.read(key.fd, min(8192, limits.output_bytes + 1 - len(output)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > limits.output_bytes:
                        stopped = "output_limit"
                        break
                if stopped:
                    break
            if not stopped:
                remaining = limits.wall_seconds - (time.monotonic() - started)
                try:
                    child.wait(timeout=max(0.001, remaining))
                except subprocess.TimeoutExpired:
                    stopped = "wall_timeout"
    finally:
        # bwrap --die-with-parent + private PID init propagates death to sandbox
        # descendants, including children that create a new session themselves.
        if child.poll() is None or stopped:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child.wait()
        child.stdout.close()
    return {"exit_code": child.returncode, "output": bytes(output[:limits.output_bytes]).decode("utf-8", "replace"),
            "termination": stopped, "output_bytes": min(len(output), limits.output_bytes)}


class BubblewrapExecutor:
    """Small Linux profile for this two-file Python fixture, not a general VM.

    System runtime is /usr/bin/python3, independently of the host's venv.
    No install, privilege elevation, host settings changes, or unsafe fallback.
    """
    name = "bubblewrap"

    def __init__(self, limits=None):
        self.limits = limits or SandboxLimits()
        self.bwrap = shutil.which("bwrap")
        self._probe = None

    def command(self, snapshot, program, status_fd):
        if sys.platform != "linux" or not self.bwrap:
            raise SandboxUnavailable("V11 needs Linux and an installed Bubblewrap executable")
        if os.geteuid() == 0:
            raise SandboxUnavailable("V11 refuses root execution; use an unprivileged account")
        if not Path("/usr/bin/python3").is_file():
            raise SandboxUnavailable("The V11 profile requires /usr/bin/python3")
        args = [self.bwrap, "--unshare-user", "--unshare-pid", "--unshare-net",
                "--unshare-ipc", "--unshare-uts", "--disable-userns",
                "--cap-drop", "ALL", "--new-session", "--die-with-parent",
                "--clearenv", "--json-status-fd", str(status_fd)]
        for path in ("/usr/bin", "/usr/lib", "/usr/lib64"):
            if Path(path).is_dir():
                args += ["--ro-bind", path, path]
        for path in ("/bin", "/lib", "/lib64"):
            if Path(path).is_symlink():
                args += ["--symlink", os.readlink(path), path]
            elif Path(path).is_dir():
                args += ["--ro-bind", path, path]
        args += ["--proc", "/proc", "--dir", "/dev"]
        for name in ("null", "urandom"):
            args += ["--dev-bind", f"/dev/{name}", f"/dev/{name}"]
        args += ["--size", str(self.limits.scratch_bytes), "--tmpfs", "/tmp",
                 "--ro-bind", str(snapshot), "/workspace", "--chdir", "/workspace",
                 "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
                 "--setenv", "TMPDIR", "/tmp", "--setenv", "LC_ALL", "C.UTF-8",
                 "--remount-ro", "/proc", "--remount-ro", "/", "--", "/usr/bin/python3", "-I", "-S", "-B", "-c", program]
        launcher = Path(__file__).with_name("_sandbox_launcher.py").resolve()
        return [sys.executable, "-I", "-S", str(launcher), json.dumps(asdict(self.limits)), *args]

    def _execute(self, snapshot, program):
        # The status fd belongs to bwrap, is closed before the payload, and is
        # never exposed as a file in the sandbox. Do not trust payload stdout to
        # attest that isolation was established.
        try:
            with tempfile.TemporaryFile() as status:
                result = collect_bounded(self.command(snapshot, program, status.fileno()),
                                         limits=self.limits, pass_fds=(status.fileno(),))
                status.seek(0)
                raw = status.read(16_385)
            if len(raw) > 16_384:
                raise SandboxUnavailable("Bubblewrap status exceeded limit")
            records = [json.loads(line) for line in raw.splitlines() if line]
            started = any(isinstance(r, dict) and isinstance(r.get("child-pid"), int) for r in records)
            if not started:
                raise SandboxUnavailable("Bubblewrap failed to establish isolation: " + result["output"][-2000:])
            exits = [r["exit-code"] for r in records if isinstance(r, dict) and "exit-code" in r]
            if not result["termination"] and (not exits or exits[-1] != result["exit_code"]):
                raise SandboxUnavailable("Missing or inconsistent Bubblewrap completion status: " + result["output"][-2000:])
            return result
        except (OSError, ValueError) as error:
            raise SandboxUnavailable(f"Sandbox startup/status failure: {error}") from error

    def preflight(self):
        if self._probe is not None:
            return self._probe
        with tempfile.TemporaryDirectory(prefix="simple-agent-probe-") as temp:
            result = self._execute(Path(temp), PROBE_PROGRAM)
        if result["exit_code"] != 0 or result["termination"]:
            raise SandboxUnavailable("Sandbox runtime probe failed: " + result["output"][-2000:])
        try:
            probe = json.loads(result["output"])
            status = dict(line.split(":", 1) for line in probe["status"].splitlines() if ":" in line)
            if (probe["net"] == os.readlink("/proc/self/ns/net") or
                    probe["pid"] == os.readlink("/proc/self/ns/pid") or
                    int(status["CapEff"].strip(), 16) != 0 or status["NoNewPrivs"].strip() != "1"):
                raise ValueError("namespace/capability/no-new-privileges checks failed")
            if tuple(map(int, probe["python"].split(".")[:2])) < (3, 10):
                raise ValueError("sandbox Python must be >=3.10")
        except (KeyError, ValueError, TypeError) as error:
            raise SandboxUnavailable(f"Sandbox probe could not verify its boundary: {error}") from error
        self._probe = {"backend": self.name, "isolated": True, "python": probe["python"],
                       "network": "private namespace, no host/external network",
                       "inputs": list(TEST_INPUTS), "limits": asdict(self.limits)}
        return self._probe

    def run_tests(self, root):
        evidence = self.preflight()
        with tempfile.TemporaryDirectory(prefix="simple-agent-snapshot-") as temp:
            snapshot = Path(temp)
            hashes = stage_inputs(root, snapshot)
            result = self._execute(snapshot, TEST_PROGRAM)
        return result | {"ok": True, "passed": result["exit_code"] == 0 and not result["termination"],
                         "command": "/usr/bin/python3 -I -S -B <fixed unittest bootstrap>",
                         "execution": evidence, "input_fingerprint": hashes}
