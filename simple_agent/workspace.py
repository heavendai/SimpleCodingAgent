"""File boundary and trusted-fixture test execution. NOT a security sandbox."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import tempfile


from .execution import TrustedHostExecutor


class BoundaryError(ValueError):
    pass


class Workspace:
    def __init__(self, root: Path, executor=None):
        self.root = root.resolve(strict=True)
        self.executor = executor or TrustedHostExecutor()

    def path(self, name: str) -> Path:
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise BoundaryError("Only nonempty repository-relative paths are allowed")
        if ".." in Path(name).parts:
            raise BoundaryError("Parent traversal is forbidden")
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise BoundaryError("Path escapes repository (possibly a symlink)")
        # Secret names and hidden directories are outside this toy tool contract.
        if any(part.startswith(".") for part in Path(name).parts + path.relative_to(self.root).parts):
            raise BoundaryError("Hidden paths are excluded")
        return path

    def read(self, path: str) -> dict:
        target = self.path(path)
        if target.stat().st_size > 32_000:
            raise BoundaryError("Demo read limit: 32 KB per file")
        return {"ok": True, "content": target.read_text(encoding="utf-8")}

    def files(self) -> list[str]:
        result = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root).as_posix()
            if not p.is_file() or p.is_symlink() or "__pycache__" in p.parts:
                continue
            if any(x.startswith(".") for x in p.relative_to(self.root).parts):
                continue
            if p.stat().st_size <= 32_000:
                result.append(rel)
        return result[:100]

    def search(self, query: str) -> dict:
        if not isinstance(query, str) or not query or len(query) > 100:
            raise ValueError("query must contain 1-100 characters")
        hits = []
        for name in self.files():
            for i, line in enumerate(self.read(name)["content"].splitlines(), 1):
                if query in line:
                    hits.append({"path": name, "line": i, "text": line[:160]})
        return {"ok": True, "hits": hits[:20]}

    def patch(self, path: str, old: str, new: str) -> dict:
        if path != "stats.py":
            raise BoundaryError("This exercise permits editing stats.py only")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("A nonempty exact old string and text new are required")
        if len(new) > 16_000:
            raise ValueError("Replacement too large")
        if (self.root / path).is_symlink():
            raise BoundaryError("Symlink edit targets are forbidden")
        target = self.path(path)
        before = self.read(path)["content"]
        if before.count(old) != 1:
            raise ValueError("Patch conflict: old text must occur exactly once; read again")
        after = before.replace(old, new, 1)
        atomic_json_or_text(target, after)
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                            fromfile=f"a/{path}", tofile=f"b/{path}"))
        return {"ok": True, "content": after, "diff": diff}

    def run_tests(self) -> dict:
        before = self.fingerprint()
        result = self.executor.run_tests(self.root)
        after = self.fingerprint()
        if after != before:
            result["output"] += "\nWorkspace changed during tests; evidence is invalid."
        inputs_match = ("input_fingerprint" not in result or
                        all(before.get(name) == digest for name, digest in result["input_fingerprint"].items()))
        if not inputs_match:
            result["output"] += "\nSnapshot differed from pre-execution files; evidence is invalid."
        result["passed"] = bool(result["passed"] and before == after and inputs_match)
        result["fingerprint"] = after
        return result

    def fingerprint(self) -> dict:
        # Integrity inventory is separate from bounded retrieval. Hidden paths and
        # bytecode caches are deliberately out of scope; symlink metadata is kept.
        result = {}
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root)
            if any(p.startswith(".") or p == "__pycache__" for p in relative.parts):
                continue
            if path.is_symlink():
                result[relative.as_posix()] = "symlink:" + os.readlink(path)
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(65536), b""):
                        digest.update(chunk)
                result[relative.as_posix()] = digest.hexdigest()
        return result


def atomic_json_or_text(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
