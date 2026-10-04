"""V11 tests do not require working namespaces; live tests skip if blocked."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from simple_agent.cli import PROJECT, build, fresh_run, run_version
from simple_agent.execution import (BubblewrapExecutor, SandboxLimits, SandboxUnavailable,
                                    TEST_INPUTS, collect_bounded, stage_inputs)
from simple_agent.protocol import State
from simple_agent.workspace import Workspace


@unittest.skipUnless(sys.platform == "linux", "Linux snapshot/profile unit tests")
class SandboxUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = fresh_run(11, self.temp.name)
        self.root = self.run_dir / "workspace"
        self.snapshot = Path(self.temp.name) / "snapshot"
        self.snapshot.mkdir()

    def test_limits_reject_invalid_values(self):
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SandboxLimits(wall_seconds=value)
        with self.assertRaises(ValueError):
            SandboxLimits(processes=1.5)

    def test_manifest_excludes_hidden_unknown_and_guidance(self):
        (self.root / ".env").write_text("fake-sentinel")
        (self.root / "other.py").write_text("raise AssertionError")
        hashes = stage_inputs(self.root, self.snapshot)
        files = sorted(p.relative_to(self.snapshot).as_posix() for p in self.snapshot.rglob("*") if p.is_file())
        self.assertEqual(files, list(TEST_INPUTS))
        self.assertEqual(hashes["stats.py"], hashlib.sha256((self.root / "stats.py").read_bytes()).hexdigest())

    def test_snapshot_rejects_leaf_symlink(self):
        (self.root / "stats.py").unlink()
        (self.root / "stats.py").symlink_to(self.root / "README.md")
        with self.assertRaises(SandboxUnavailable):
            stage_inputs(self.root, self.snapshot)

    def test_snapshot_rejects_parent_symlink(self):
        (self.root / "tests").rename(self.root / "real_tests")
        (self.root / "tests").symlink_to(self.root / "real_tests", target_is_directory=True)
        with self.assertRaises(SandboxUnavailable):
            stage_inputs(self.root, self.snapshot)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO test")
    def test_snapshot_rejects_fifo_without_blocking(self):
        (self.root / "stats.py").unlink()
        os.mkfifo(self.root / "stats.py")
        with self.assertRaises(SandboxUnavailable):
            stage_inputs(self.root, self.snapshot)

    def test_snapshot_rejects_large_file(self):
        (self.root / "stats.py").write_bytes(b"x" * 65537)
        with self.assertRaises(SandboxUnavailable):
            stage_inputs(self.root, self.snapshot)

    def test_missing_runtime_fails_closed(self):
        executor = BubblewrapExecutor()
        executor.bwrap = None
        with patch("simple_agent.execution.TrustedHostExecutor.run_tests") as host:
            with self.assertRaises(SandboxUnavailable):
                executor.run_tests(self.root)
            host.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux", "Linux profile construction")
    def test_profile_has_mandatory_boundaries_and_no_host_repo_mount(self):
        executor = BubblewrapExecutor()
        executor.bwrap = "/usr/bin/bwrap"
        with patch("os.geteuid", return_value=1000):
            args = executor.command(self.snapshot, "print('unit probe')", 17)
        for option in ("--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc",
                       "--unshare-uts", "--disable-userns", "--die-with-parent", "--new-session", "--clearenv"):
            self.assertIn(option, args)
        for option in ("--share-net", "--unshare-user-try", "--bind", "--dev", "--not-a-security-boundary"):
            self.assertNotIn(option, args)
        self.assertNotIn(str(self.root), args)
        self.assertIn("/usr/bin/python3", args)
        self.assertEqual(args[1:3], ["-I", "-S"])
        self.assertEqual(args[args.index("--cap-drop") + 1], "ALL")
        mounts = [args[i + 1] for i, x in enumerate(args) if x == "--remount-ro"]
        self.assertEqual(mounts, ["/proc", "/"])
        devices = [args[i + 1] for i, x in enumerate(args) if x == "--dev-bind"]
        self.assertEqual(devices, ["/dev/null", "/dev/urandom"])

    def test_preflight_blocks_before_model_and_records_checkpoint(self):
        with patch.object(BubblewrapExecutor, "preflight", side_effect=SandboxUnavailable("test denial")), \
             patch("simple_agent.execution.TrustedHostExecutor.run_tests") as host:
            result, agent = run_version(11, self.temp.name, quiet=True)
        self.assertEqual(result["status"], "blocked_sandbox")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["patches"], 0)
        self.assertEqual(result["test_outcomes"], [])
        self.assertEqual(json.loads(agent.checkpoint_path.read_text())["state"]["status"], "blocked_sandbox")
        host.assert_not_called()

    def test_setup_failure_after_preflight_stops_without_repair_or_fallback(self):
        with patch.object(BubblewrapExecutor, "preflight", return_value={"backend": "bubblewrap", "isolated": True}), \
             patch.object(BubblewrapExecutor, "run_tests", side_effect=SandboxUnavailable("later denial")), \
             patch("simple_agent.execution.TrustedHostExecutor.run_tests") as host:
            agent = build(11, self.root)
            agent.run()
        self.assertEqual(agent.state.status, "blocked_sandbox")
        self.assertEqual(agent.state.facts["patches"], 0)
        host.assert_not_called()

    def test_host_checkpoint_cannot_be_restored_as_sandbox(self):
        agent = build(10, self.root)
        agent.save_checkpoint()
        with self.assertRaisesRegex(ValueError, "execution backend"):
            build(11, self.root).restore(agent.checkpoint_path)

    def test_sandbox_checkpoint_cannot_downgrade_to_host(self):
        agent = build(11, self.root)
        agent.save_checkpoint()
        with self.assertRaisesRegex(ValueError, "execution backend"):
            build(10, self.root).restore(agent.checkpoint_path)

    def test_host_passing_evidence_is_not_sandbox_evidence(self):
        agent = build(11, self.root)
        agent.state.observe("run_tests", {}, {"ok": True, "passed": True, "output": "",
            "fingerprint": agent.workspace.fingerprint(),
            "execution": {"backend": "trusted-host", "isolated": False}})
        self.assertFalse(agent.verified())
        agent.state.facts["tests"][-1]["execution"] = {"backend": "bubblewrap", "isolated": True}
        self.assertTrue(agent.verified())
        agent.state.facts["tests"][-1]["execution"] = None
        self.assertFalse(agent.verified())

    def test_saved_verified_status_does_not_skip_evidence_gate(self):
        agent = build(11, self.root)
        agent.preflight = lambda: {"backend": "bubblewrap", "isolated": True}
        agent.state.status = "verified"
        agent.run()
        self.assertEqual(agent.state.status, "unverified_completion_rejected")

    def test_snapshot_hash_mismatch_invalidates_pass(self):
        executor = BubblewrapExecutor()
        with patch.object(executor, "run_tests", return_value={"ok": True, "passed": True,
             "output": "", "input_fingerprint": {"stats.py": "wrong"}}):
            result = Workspace(self.root, executor).run_tests()
        self.assertFalse(result["passed"])

    def test_stdout_cannot_forge_bubblewrap_status(self):
        executor = BubblewrapExecutor()
        with patch.object(executor, "command", return_value=["unused"]), \
             patch("simple_agent.execution.collect_bounded", return_value={
                 "exit_code": 0, "termination": None, "output": '{"child-pid": 1, "exit-code": 0}'}):
            with self.assertRaisesRegex(SandboxUnavailable, "establish isolation"):
                executor._execute(self.snapshot, "unused")

    def test_blocked_cli_exits_nonzero(self):
        script = ("from unittest.mock import patch; from simple_agent.execution import BubblewrapExecutor, SandboxUnavailable; "
                  "from simple_agent.cli import main; "
                  "patch.object(BubblewrapExecutor,'preflight',side_effect=SandboxUnavailable('test denied')).start(); main()")
        done = subprocess.run([sys.executable, "-c", script, "--version", "11", "--output", self.temp.name],
                              cwd=PROJECT, capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 1)
        self.assertIn("blocked_sandbox", done.stdout)


@unittest.skipUnless(os.name == "posix", "POSIX bounded process collector")
class CollectorTests(unittest.TestCase):
    def collect(self, program, **limits):
        # These are trusted test-owned snippets, not model/repository code.
        return collect_bounded([sys.executable, "-I", "-S", "-c", program], limits=SandboxLimits(**limits))

    def test_small_stdout_stderr_and_invalid_utf8(self):
        result = self.collect("import os; os.write(1,b'hello'); os.write(2,b'\\xff')")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"], "hello\ufffd")

    def test_output_capped_while_running(self):
        result = self.collect("import os;\nwhile True: os.write(1,b'x'*8192)", output_bytes=1024)
        self.assertEqual(result["termination"], "output_limit")
        self.assertEqual(len(result["output"]), 1024)

    def test_wall_timeout(self):
        started = time.monotonic()
        result = self.collect("import time; time.sleep(10)", wall_seconds=0.15)
        self.assertEqual(result["termination"], "wall_timeout")
        self.assertLess(time.monotonic() - started, 3)

    def test_closed_output_still_has_wall_deadline(self):
        result = self.collect("import os,time; os.close(1); os.close(2); time.sleep(10)", wall_seconds=0.15)
        self.assertEqual(result["termination"], "wall_timeout")

    @unittest.skipUnless(sys.platform == "linux", "Linux resource limits")
    def test_trusted_launcher_inherits_finite_hard_limits(self):
        from dataclasses import asdict
        launcher = PROJECT / "simple_agent" / "_sandbox_launcher.py"
        program = ("import resource,json; names=['CPU','AS','FSIZE','NOFILE','NPROC','CORE']; "
                   "print(json.dumps({n:resource.getrlimit(getattr(resource,'RLIMIT_'+n)) for n in names}))")
        result = collect_bounded([sys.executable, "-I", "-S", str(launcher), json.dumps(asdict(SandboxLimits())),
                                  sys.executable, "-I", "-S", "-c", program], limits=SandboxLimits())
        self.assertEqual(result["exit_code"], 0, result)
        values = json.loads(result["output"])
        for name, bound in {"CPU": 3, "AS": 268435456, "FSIZE": 1048576, "NOFILE": 64, "NPROC": 64, "CORE": 0}.items():
            self.assertGreaterEqual(values[name][1], 0)
            self.assertLessEqual(values[name][1], bound)
            self.assertEqual(values[name][0], values[name][1])

    def test_child_holding_pipe_is_bounded(self):
        program = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'])"
        result = self.collect(program, wall_seconds=0.15)
        self.assertEqual(result["termination"], "wall_timeout")

    def test_inherited_environment_and_stdin_are_empty(self):
        with patch.dict(os.environ, {"SIMPLE_FAKE_SECRET": "sentinel"}):
            result = self.collect("import os,sys; print('SIMPLE_FAKE_SECRET' in os.environ); print(repr(sys.stdin.read()))")
        self.assertEqual(result["output"], "False\n''\n")

    def test_launch_error_is_not_turned_into_success(self):
        with self.assertRaises(FileNotFoundError):
            collect_bounded(["/nonexistent-simple-agent-test"], limits=SandboxLimits())


class LiveSandboxTests(unittest.TestCase):
    """Never run a live payload unless the exact mandatory profile probes OK."""
    @classmethod
    def setUpClass(cls):
        cls.executor = BubblewrapExecutor()
        cls.blocker = None
        try:
            cls.executor.preflight()
        except SandboxUnavailable as error:
            cls.blocker = str(error)

    def setUp(self):
        if self.blocker:
            self.skipTest("LIVE SANDBOX NOT RUN: " + self.blocker)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def execute(self, program):
        result = self.executor._execute(self.root, program)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertIsNone(result["termination"], result)
        return result

    def test_private_namespaces_and_runtime_probe(self):
        report = self.executor.preflight()
        self.assertTrue(report["isolated"])
        self.assertEqual(report["backend"], "bubblewrap")

    def test_only_tmp_writable(self):
        self.execute("from pathlib import Path; import errno\n"
            "for path in ['/blocked','/workspace/blocked','/dev/blocked']:\n"
            " try: Path(path).write_text('x')\n"
            " except OSError as e: assert e.errno in (errno.EROFS,errno.EACCES,errno.EPERM)\n"
            " else: raise AssertionError(path)\n"
            "Path('/tmp/allowed').write_text('ok')")

    def test_host_canary_hidden(self):
        with tempfile.TemporaryDirectory() as outside:
            canary = Path(outside) / "fake-private-canary"
            canary.write_text("public-test-sentinel")
            self.execute(f"from pathlib import Path; assert not Path({str(canary)!r}).exists(); assert not Path('/home').exists()")

    def test_host_loopback_service_inaccessible(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.execute("import socket\ntry: socket.create_connection(('127.0.0.1'," + str(port) + "),.2)\n"
                         "except OSError: pass\nelse: raise AssertionError('host network reached')")

    def test_environment_and_extra_fd_not_inherited(self):
        with patch.dict(os.environ, {"SIMPLE_FAKE_SECRET": "sentinel"}):
            self.execute("import os; assert 'SIMPLE_FAKE_SECRET' not in os.environ; "
                         "assert not [n for n in os.listdir('/proc/self/fd') if int(n)>3]")

    def test_hard_resource_limits_present(self):
        self.execute("import resource; "
            "assert 0<=resource.getrlimit(resource.RLIMIT_CPU)[1]<=3; "
            "assert 0<=resource.getrlimit(resource.RLIMIT_AS)[1]<=268435456; "
            "assert 0<=resource.getrlimit(resource.RLIMIT_NOFILE)[1]<=64; "
            "assert 0<=resource.getrlimit(resource.RLIMIT_NPROC)[1]<=64; "
            "assert 0<=resource.getrlimit(resource.RLIMIT_FSIZE)[1]<=1048576; "
            "assert resource.getrlimit(resource.RLIMIT_CORE)==(0,0)")

    def test_timeout_of_detached_descendant(self):
        executor = BubblewrapExecutor(replace(SandboxLimits(), wall_seconds=0.4))
        executor.preflight()
        started = time.monotonic()
        program = "import os,time\nif os.fork()==0:\n os.setsid(); time.sleep(20)\nelse: time.sleep(20)"
        with tempfile.TemporaryFile() as status:
            result = collect_bounded(executor.command(self.root, program, status.fileno()),
                                     limits=executor.limits, pass_fds=(status.fileno(),))
            status.seek(0)
            records = [json.loads(line) for line in status.read().splitlines()]
        self.assertEqual(result["termination"], "wall_timeout")
        child = next(r for r in records if "child-pid" in r)
        self.assertIn("pid-namespace", child)
        namespace = f"pid:[{child['pid-namespace']}]"
        deadline = time.monotonic() + 2
        def same_namespace_still_alive():
            try:
                return os.readlink(f"/proc/{child['child-pid']}/ns/pid") == namespace
            except FileNotFoundError:
                return False
        while same_namespace_still_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(same_namespace_still_alive(), "sandbox namespace init survived timeout")
        self.assertLess(time.monotonic() - started, 3)

    def test_v11_end_to_end(self):
        summary, agent = run_version(11, self.temp.name, quiet=True)
        self.assertEqual(summary["status"], "verified")
        self.assertEqual(summary["test_outcomes"], [False, False, True])
        self.assertTrue(all(t["execution"]["isolated"] for t in agent.state.facts["tests"]))


if __name__ == "__main__":
    unittest.main()
