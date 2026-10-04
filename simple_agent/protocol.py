"""V01: a provider-neutral, validated model/action contract."""
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Decision:
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    final: str | None = None

    @classmethod
    def parse(cls, raw: dict) -> "Decision":
        if not isinstance(raw, dict) or set(raw) - {"tool", "arguments", "final"}:
            raise ValueError("Unknown decision fields")
        tool, final = raw.get("tool"), raw.get("final")
        if (tool is None) == (final is None):
            raise ValueError("Exactly one of tool or final is required")
        if tool is not None and (not isinstance(tool, str) or not tool):
            raise ValueError("tool must be a nonempty string")
        if final is not None and not isinstance(final, str):
            raise ValueError("final must be text")
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        if final is not None and arguments:
            raise ValueError("final cannot contain tool arguments")
        return cls(tool, arguments, final)


class Model(Protocol):
    name: str

    def next(self, context: dict, tools: list[str]) -> Decision: ...


@dataclass
class State:
    goal: str
    history: list[dict] = field(default_factory=list)
    facts: dict = field(default_factory=lambda: {
        "files": {}, "patches": 0, "tests": [], "review": None,
        "plan": [], "repo": None, "skills": {}, "read_paths": [],
    })
    summary: str = ""
    final: str | None = None
    status: str = "running"
    steps: int = 0
    pending: dict | None = None

    def observe(self, tool: str, arguments: dict, result: dict):
        self.history.append({"tool": tool, "arguments": arguments, "result": result})
        if not result.get("ok"):
            return
        if tool in {"read", "patch"}:
            self.facts["files"][arguments["path"]] = result["content"]
            if tool == "read":
                self.facts["read_paths"].append(arguments["path"])
            else:
                self.facts["patches"] += 1
                self.facts["review"] = None
        if tool == "run_tests":
            self.facts["tests"].append({
                "passed": result["passed"], "patches": self.facts["patches"],
                "output": result["output"], "fingerprint": result.get("fingerprint"),
                "execution": result.get("execution"),
            })
        if tool == "set_plan":
            self.facts["plan"] = result["steps"]
        if tool == "repo_context":
            self.facts["repo"] = result
        if tool == "load_skill":
            self.facts["skills"][arguments["name"]] = result["content"]
        if tool == "delegate_review":
            self.facts["review"] = result

    def compact(self, max_history_chars=2600):
        """V06: deterministic facts, not hidden reasoning or an LLM summary."""
        import json
        before = len(json.dumps(self.history, ensure_ascii=False))
        if before <= max_history_chars:
            return False
        self.summary = (
            f"Read {self.facts['read_paths']}; patches={self.facts['patches']}; "
            f"test outcomes={[x['passed'] for x in self.facts['tests']]}. "
            "Current file snapshots and plan stay in structured facts."
        )
        self.history = self.history[-2:]
        return True

    def context(self) -> dict:
        return {"goal": self.goal, "summary": self.summary,
                "facts": self.facts, "recent_observations": self.history[-4:]}
