"""One CLI, eleven small construction recipes. No external dependency or network."""
import argparse
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import shutil
import tempfile

from .workspace import atomic_json_or_text

PROJECT = Path(__file__).resolve().parent.parent


def fresh_run(version, output=None):
    parent = Path(output).resolve() if output else PROJECT / "runs"
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=f"v{version:02d}-", dir=parent))
    shutil.copytree(PROJECT / "examples" / "buggy_repo", run_dir / "workspace",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return run_dir


def build(version, root, **kwargs):
    return importlib.import_module(f"versions.v{version:02d}").build(root, **kwargs)


def run_version(version, output=None, *, approval_demo=False, require_approval=False,
                pause_after=None, resume=None, approve_pending=False, quiet=False):
    if require_approval and version < 5:
        raise ValueError("Write approval is introduced in V05; use V05 or later")
    if resume:
        run_dir = Path(resume).resolve()
        metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        if metadata["version"] != version:
            raise ValueError("Resume version does not match run.json")
        require_approval = metadata["require_approval"]
    else:
        run_dir = fresh_run(version, output)
        atomic_json_or_text(run_dir / "run.json", {
            "version": version, "require_approval": require_approval or approval_demo})
    agent = build(version, run_dir / "workspace",
                  require_approval=require_approval or approval_demo)
    if resume:
        agent.restore(run_dir / "checkpoint.json")
        if approve_pending:
            if not agent.state.pending:
                raise ValueError("No exact pending action to approve")
            action = agent.state.pending
            agent.policy.approve_once(action["tool"], action["arguments"])
    # V08 default demonstrates restore using a fresh Engine instance.
    if version == 8 and not resume and not pause_after:
        agent.run(pause_after=3)
        first_events = list(agent.events)
        agent = build(version, run_dir / "workspace",
                      require_approval=require_approval or approval_demo)
        agent.restore(run_dir / "checkpoint.json")
        agent.events = first_events + agent.events
    state = agent.run(pause_after=pause_after)
    if approval_demo and state.status == "awaiting_approval":
        action = state.pending
        if not quiet:
            print("[演示] 写入被拦截。现在模拟 host 对下面这一个补丁的批准：")
            print(json.dumps(action, ensure_ascii=False, indent=2))
        agent.policy.approve_once(action["tool"], action["arguments"])
        state = agent.run()
    summary = {
        "version": version, "status": state.status, "message": state.final,
        "patches": state.facts["patches"],
        "test_outcomes": [t["passed"] for t in state.facts["tests"]],
        "model_calls": agent.budget.calls, "tool_calls": agent.budget.tool_calls,
        "model_characters": agent.budget.model_chars,
        "run_dir": str(run_dir), "plan": state.facts["plan"],
        "compacted": bool(state.summary),
        "execution_backend": agent.workspace.executor.name,
    }
    atomic_json_or_text(run_dir / "result.json", summary)
    atomic_json_or_text(run_dir / "events.json", agent.events)
    if not quiet:
        title = importlib.import_module(f"versions.v{version:02d}").TITLE
        print(f"\nV{version:02d} {title}: {state.status}")
        print(state.final or f"Paused. Pending: {state.pending}")
        print(f"patches={summary['patches']}; tests={summary['test_outcomes']}; "
              f"model_calls={summary['model_calls']}")
        print(f"Artifacts: {run_dir}")
    return summary, agent


def main(default_version=None):
    parser = argparse.ArgumentParser(description="SimpleCodingAgent: eleven offline lessons")
    parser.add_argument("--version", type=int, choices=range(1, 12), default=default_version)
    parser.add_argument("--all", action="store_true", help="Run V01-V11; sandbox failure is a nonzero result")
    parser.add_argument("--legacy-all", action="store_true", help="Run trusted teaching fixtures V01-V10 only")
    parser.add_argument("--output", help="Parent directory for fresh, unique run folders")
    parser.add_argument("--approval-demo", action="store_true",
                        help="Simulate one exact host approval in the trusted exercise")
    parser.add_argument("--require-approval", action="store_true")
    parser.add_argument("--pause-after", type=int, help="Pause after N actions, V08+")
    parser.add_argument("--resume", help="Existing run folder, V08+")
    parser.add_argument("--approve-pending", action="store_true")
    args = parser.parse_args()
    if args.all and args.legacy_all:
        parser.error("Choose only one of --all and --legacy-all")
    multiple = args.all or args.legacy_all
    if not multiple and args.version is None:
        parser.error("Choose --version 1..11 or --all")
    if multiple and (args.resume or args.pause_after or args.require_approval):
        parser.error("Resume/pause/required-approval need a single version")
    if (args.resume or args.pause_after) and (args.version is None or args.version < 8):
        parser.error("Durable pause/resume is introduced in V08")
    if args.require_approval and (args.version is None or args.version < 5):
        parser.error("Write approval is introduced in V05; use V05 or later")
    if args.pause_after is not None and args.pause_after < 1:
        parser.error("--pause-after must be positive")
    if args.approve_pending and not args.resume:
        parser.error("--approve-pending requires --resume")
    if args.approval_demo and (multiple or args.version is None or args.version < 5):
        parser.error("--approval-demo needs one version >= 5")
    versions = range(1, 12) if args.all else range(1, 11) if args.legacy_all else [args.version]
    results = []
    for version in versions:
        result, _ = run_version(version, args.output, approval_demo=args.approval_demo,
                                require_approval=args.require_approval,
                                pause_after=args.pause_after, resume=args.resume,
                                approve_pending=args.approve_pending)
        results.append(result)
    if multiple:
        destination = Path(args.output).resolve() if args.output else PROJECT / "runs"
        atomic_json_or_text(destination / "all-results.json", results)
    failed = any(x["status"] in {"stopped", "unverified_completion_rejected", "blocked_sandbox"} for x in results)
    raise SystemExit(1 if failed else 0)
