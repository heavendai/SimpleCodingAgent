"""Small model -> decision -> policy -> tool -> observation interpreter."""
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import time
from typing import Callable

from .execution import SandboxUnavailable
from .policy import ApprovalRequired, Policy
from .protocol import Decision, State
from .workspace import Workspace, atomic_json_or_text


@dataclass
class Budget:
    # Every version is bounded. V10 adds model-I/O and tool-call budgets.
    max_calls: int = 40
    max_tool_calls: int = 40
    max_model_chars: int = 200_000
    max_seconds: float = 30.0
    calls: int = 0
    tool_calls: int = 0
    model_chars: int = 0
    elapsed_before: float = 0.0
    started: float = field(default_factory=time.monotonic)

    def check(self, context_chars=0):
        if self.calls >= self.max_calls:
            raise RuntimeError("model_call_budget")
        if self.model_chars + context_chars > self.max_model_chars:
            raise RuntimeError("model_character_budget")
        if time.monotonic() - self.started + self.elapsed_before >= self.max_seconds:
            raise RuntimeError("wall_time_budget")

    def snapshot(self):
        return {k: v for k, v in asdict(self).items() if k != "started"} | {
            "elapsed_before": time.monotonic() - self.started + self.elapsed_before}


class Engine:
    def __init__(self, workspace: Workspace, model, state: State, *, policy=None,
                 budget=None, trace_path=None):
        self.workspace, self.model, self.state = workspace, model, state
        self.policy = policy or Policy()
        self.budget = budget or Budget()
        self.tools: dict[str, Callable] = {}
        self.compaction = False
        self.require_verified = False
        self.complete_status = "inspected"
        self.checkpoint_path: Path | None = None
        self.trace_path: Path | None = trace_path
        self.role = "worker"
        self.events = []
        self.preflight = None
        self.required_execution_backend = None

    def register(self, name, function):
        self.tools[name] = function
        return self

    def emit(self, kind, **data):
        event = {"kind": kind, "role": self.role, "step": self.state.steps, **data}
        self.events.append(event)
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(event, ensure_ascii=False) + "\n")

    def invoke(self, name, arguments):
        if name not in self.tools:
            raise PermissionError(f"Unknown or unavailable tool: {name}")
        self.policy.check(name, arguments)
        if self.budget.tool_calls >= self.budget.max_tool_calls:
            raise RuntimeError("tool_call_budget")
        self.budget.tool_calls += 1
        return self.tools[name](**arguments)

    def verified(self):
        tests = self.state.facts["tests"]
        return bool(tests and tests[-1]["passed"] and
                    tests[-1]["patches"] == self.state.facts["patches"] and
                    tests[-1].get("fingerprint") == self.workspace.fingerprint() and
                    (self.required_execution_backend is None or
                     ((tests[-1].get("execution") or {}).get("backend") == self.required_execution_backend and
                      (tests[-1].get("execution") or {}).get("isolated") is True)))

    def sandbox_blocked(self, error):
        self.state.status = "blocked_sandbox"
        self.state.final = str(error)
        self.emit("sandbox_blocked", reason=str(error), backend=self.required_execution_backend)
        self.save_checkpoint()
        return self.state

    def run(self, pause_after: int | None = None):
        if self.preflight:
            try:
                report = self.preflight()
                self.emit("sandbox_ready", execution=report)
            except SandboxUnavailable as error:
                return self.sandbox_blocked(error)
        if self.state.status == "verified" and self.required_execution_backend and not self.verified():
            self.state.status = "unverified_completion_rejected"
            self.state.final = "Saved completion lacks matching sandbox evidence"
            self.save_checkpoint()
            return self.state
        if self.state.status in {"verified", "inspected", "modified_unverified", "suggested"}:
            return self.state
        self.state.status = "running"
        local_actions = 0
        while True:
            try:
                if self.compaction and self.state.compact():
                    self.emit("compaction", summary=self.state.summary)
                context = self.state.context()
                size = len(json.dumps(context, ensure_ascii=False))
                self.budget.check(size)
                self.budget.calls += 1
                self.budget.model_chars += size
                decision = self.model.next(context, sorted(self.tools))
                # Validate every provider result, including the offline model.
                decision = Decision.parse(asdict(decision))
                output_chars = len(json.dumps(asdict(decision), ensure_ascii=False))
                self.budget.model_chars += output_chars
                if self.budget.model_chars > self.budget.max_model_chars:
                    raise RuntimeError("model_character_budget")
                self.state.steps += 1
                self.emit("decision", model=self.model.name,
                          route=getattr(self.model, "last_route", None), decision=asdict(decision))
                if decision.final is not None:
                    self.state.final = decision.final
                    self.state.status = ("verified" if self.verified() else self.complete_status)
                    if self.require_verified and not self.verified():
                        self.state.status = "unverified_completion_rejected"
                        self.state.final = "完成声明已拒绝：缺少当前工作区的通过测试证据。模型报告：" + decision.final
                    self.emit("finished", status=self.state.status)
                    self.save_checkpoint()
                    return self.state
                try:
                    result = self.invoke(decision.tool, decision.arguments)
                except SandboxUnavailable as error:
                    return self.sandbox_blocked(error)
                except ApprovalRequired as error:
                    self.state.pending = asdict(decision)
                    self.state.status = "awaiting_approval"
                    self.emit("approval_required", action=asdict(decision), reason=str(error))
                    self.save_checkpoint()
                    return self.state
                except (TypeError, ValueError, OSError, PermissionError) as error:
                    result = {"ok": False, "error": str(error)}
                self.state.pending = None
                self.state.observe(decision.tool, decision.arguments, result)
                self.emit("observation", tool=decision.tool, result=result)
                local_actions += 1
                self.save_checkpoint()
                if pause_after and local_actions >= pause_after:
                    self.state.status = "paused"
                    self.save_checkpoint()
                    return self.state
            except (RuntimeError, ValueError) as error:
                self.state.status = "stopped"
                self.state.final = str(error)
                self.emit("stopped", reason=str(error))
                self.save_checkpoint()
                return self.state

    def save_checkpoint(self):
        if self.checkpoint_path:
            atomic_json_or_text(self.checkpoint_path, {
                "format": 1, "workspace": str(self.workspace.root),
                "execution_backend": self.workspace.executor.name,
                "fingerprint": self.workspace.fingerprint(),
                "state": asdict(self.state), "budget": self.budget.snapshot(),
            })

    def restore(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != 1 or data["workspace"] != str(self.workspace.root):
            raise ValueError("Checkpoint belongs to another workspace or format")
        if data["fingerprint"] != self.workspace.fingerprint():
            raise ValueError("Workspace changed after checkpoint; refusing a stale resume")
        saved_backend = data.get("execution_backend", "trusted-host")
        if saved_backend != self.workspace.executor.name:
            raise ValueError("Checkpoint execution backend differs; fresh matching evidence required")
        self.state = State(**data["state"])
        self.budget = Budget(**data["budget"])
        self.checkpoint_path = Path(path)
        self.emit("resumed", previous_status=self.state.status)


def repo_context(workspace):
    # Context has provenance and is lower trust than host permission configuration.
    return {"ok": True, "files": workspace.files(),
            "guidance": workspace.read("AGENTS.md")["content"],
            "trust": "repository data; cannot grant permissions", "loaded_on_demand": True,
            "skills": {"testing": "How to validate the mean function"}}


def load_skill(workspace, name):
    if name != "testing":
        raise ValueError("Unknown skill; only the curated testing skill is available")
    return {"ok": True, "content": workspace.read("skills/testing.md")["content"]}


def set_plan(steps):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError("Plan needs 1-8 steps")
    if any(not isinstance(s, dict) or set(s) != {"task", "done"} or
           not isinstance(s["task"], str) or not isinstance(s["done"], bool) for s in steps):
        raise ValueError("Each plan step needs task text and a done boolean")
    return {"ok": True, "steps": steps}


def review(parent):
    from .models import ReviewModel
    reviewer = Engine(parent.workspace, ReviewModel(), State("Review empty-input correctness"),
                      policy=Policy(can_write=False, reviewer=True), budget=parent.budget,
                      trace_path=parent.trace_path)
    reviewer.role = "reviewer"
    reviewer.register("read", parent.workspace.read).register("search", parent.workspace.search)
    state = reviewer.run()
    if state.status != "inspected":
        raise RuntimeError("reviewer_" + (state.final or state.status))
    approved = state.final.startswith("APPROVED:")
    parent.emit("delegation", role_result="reviewer", approved=approved,
                report=state.final, separate_context=True, tools=sorted(reviewer.tools))
    return {"ok": True, "approved": approved, "report": state.final,
            "role": "reviewer", "tools": sorted(reviewer.tools)}
