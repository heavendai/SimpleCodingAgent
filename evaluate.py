"""V10 external outcome grader. Fixed toy suite, not a coding benchmark."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from simple_agent.cli import build, fresh_run
from simple_agent.models import FIXED_LINE
from simple_agent.workspace import atomic_json_or_text

CASES = [
    ("wrong_denominator", "    return sum(values) / (len(values) + 1)", True),
    ("missing_empty_guard", "    return sum(values) / len(values)", True),
    ("already_correct", FIXED_LINE, True),
    ("unsupported_implementation", "    return 42", False),
]


def grade(root):
    # Independent assertions: this grader does not read agent.final or its tests.
    program = (
        "import runpy, sys; f=runpy.run_path(sys.argv[1])['mean']; "
        "cases=[([2,4],3.0),([],0.0),([-4,-2],-3.0),([7],7.0),([0,10,20],10.0)]; "
        "assert all(f(x)==y for x,y in cases)"
    )
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", program,
                                str(root / "stats.py")], capture_output=True, text=True,
                               timeout=5, env={})
    return completed.returncode == 0


def evaluate(version=10, output=None):
    rows = []
    with tempfile.TemporaryDirectory(prefix="simple-agent-eval-") as temp:
        for name, line, expected in CASES:
            run_dir = fresh_run(version, temp)
            root = run_dir / "workspace"
            source = (root / "stats.py").read_text()
            (root / "stats.py").write_text(source.replace(source.splitlines()[-1], line))
            agent = build(version, root)
            agent.run()
            solved = grade(root)
            rows.append({"task": name, "task_solved": solved, "expected_solved": expected,
                         "harness_pass": solved == expected,
                         "status": agent.state.status, "model_calls": agent.budget.calls,
                         "tool_calls": agent.budget.tool_calls,
                         "model_characters": agent.budget.model_chars})
    report = {"version": version, "provider": "offline deterministic demonstration",
              "tasks": rows, "solved": sum(x["task_solved"] for x in rows),
              "harness_passed": sum(x["harness_pass"] for x in rows), "total": len(rows),
              "interpretation": "Toy orchestration regression only; no SOTA or general coding claim"}
    if output:
        atomic_json_or_text(Path(output), report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, choices=range(4, 11), default=10)
    parser.add_argument("--output", default="artifacts/eval-report.json")
    args = parser.parse_args()
    report = evaluate(args.version, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["harness_passed"] == report["total"] else 1)
