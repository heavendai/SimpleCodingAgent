"""Probe the exact V11 isolation profile without executing repository code."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys

from simple_agent.execution import BubblewrapExecutor, SandboxUnavailable
from simple_agent.workspace import atomic_json_or_text


def check():
    executor = BubblewrapExecutor()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "host_python": platform.python_version(), "platform": sys.platform,
              "backend": executor.name, "binary": executor.bwrap,
              "unsafe_fallback": False, "repository_code_executed": False}
    if executor.bwrap:
        try:
            report["bubblewrap_version"] = subprocess.run(
                [executor.bwrap, "--version"], capture_output=True, text=True,
                timeout=2, env={}, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            report["version_error"] = str(error)
    try:
        report["probe"] = executor.preflight()
        report["status"] = "ready"
        report["meaning"] = "Exact profile started; run live integration tests separately"
    except SandboxUnavailable as error:
        report["status"] = "blocked_sandbox"
        report["reason"] = str(error)
        report["meaning"] = "Live isolation and V11 end-to-end tests NOT RUN; no host fallback"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/sandbox-report.json")
    args = parser.parse_args()
    report = check()
    atomic_json_or_text(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "ready" else 1)
