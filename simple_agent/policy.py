"""V05: host-owned permissions; model output cannot grant itself access."""
from dataclasses import dataclass, field
import hashlib
import json


class ApprovalRequired(PermissionError):
    pass


@dataclass
class Policy:
    can_write: bool = True
    reviewer: bool = False
    approved_once: set[str] = field(default_factory=set)

    @staticmethod
    def key(tool, arguments):
        raw = json.dumps([tool, arguments], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def approve_once(self, tool, arguments):
        # Called by the human-facing host, never registered as a model tool.
        self.approved_once.add(self.key(tool, arguments))

    def check(self, tool, arguments):
        if self.reviewer and tool not in {"read", "search"}:
            raise PermissionError("Reviewer is read-only")
        if tool == "patch" and not self.can_write:
            key = self.key(tool, arguments)
            if key not in self.approved_once:
                raise ApprovalRequired("Exact patch requires host approval")
            self.approved_once.remove(key)
