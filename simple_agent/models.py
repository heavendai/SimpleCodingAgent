"""Deterministic lesson models. These teach orchestration, not LLM intelligence."""
from .protocol import Decision

FIXED_LINE = "    return sum(values) / len(values) if values else 0.0"


class DemoModel:
    name = "offline-demo"

    def __init__(self, mistake_once=False):
        self.mistake_once = mistake_once

    def next(self, context, tools):
        f = context["facts"]
        if not tools:
            return Decision(final="建议：分母使用 len(values)，并让空序列返回 0.0；尚未读写文件或验证。")
        if "set_plan" in tools and not f["plan"]:
            return Decision("set_plan", {"steps": [
                {"task": "Inspect repository and failing tests", "done": False},
                {"task": "Patch stats.py without changing tests", "done": False},
                {"task": "Verify the fix", "done": False}]})
        if "repo_context" in tools and f["repo"] is None:
            return Decision("repo_context")
        if "load_skill" in tools and "testing" not in f["skills"]:
            return Decision("load_skill", {"name": "testing"})
        if not f["read_paths"]:
            # Search is a real tool call before we read a file.
            recent = context["recent_observations"]
            if not any(x["tool"] == "search" for x in recent):
                return Decision("search", {"query": "def mean"})
        if "stats.py" not in f["files"]:
            return Decision("read", {"path": "stats.py"})
        source = f["files"]["stats.py"]
        if "patch" not in tools:
            return Decision(final="已通过 search/read 定位 mean 的分母错误；本版只有只读工具。")
        if "run_tests" in tools and not f["tests"]:
            return Decision("run_tests")
        lines = source.splitlines()
        current = next((line for line in lines if "return sum(values)" in line), None)
        if current is None:
            return Decision(final="演示模型无法识别这个函数；需要真实模型或人工处理。")
        fixed = current.strip() == FIXED_LINE.strip()
        wrong_candidate = current.strip() == "return sum(values) / len(values)"
        if "delegate_review" in tools and f["patches"] > 0 and f["review"] is None:
            return Decision("delegate_review")
        latest = f["tests"][-1] if f["tests"] else None
        reviewed_bad = f["review"] is not None and not f["review"]["approved"]
        tested_current = latest is not None and latest["patches"] == f["patches"]
        # Do not repair the deliberate bad candidate before observing feedback.
        needs_patch = not fixed and (not wrong_candidate or reviewed_bad or
                                    (tested_current and not latest["passed"]))
        if needs_patch:
            bad_first = self.mistake_once and f["patches"] == 0
            new = "    return sum(values) / len(values)" if bad_first else FIXED_LINE
            return Decision("patch", {"path": "stats.py", "old": current, "new": new})
        if "run_tests" in tools and not tested_current:
            return Decision("run_tests")
        if "set_plan" in tools and any(not p["done"] for p in f["plan"]):
            return Decision("set_plan", {"steps": [{**p, "done": True} for p in f["plan"]]})
        if latest and latest["passed"] and tested_current:
            return Decision(final="修复完成；当前代码通过提供的 4 项测试。")
        return Decision(final="补丁已写入；本版尚无执行测试的能力，结果未验证。")


class ReviewModel:
    name = "offline-reviewer"

    def next(self, context, tools):
        files = context["facts"]["files"]
        for path in ("stats.py", "tests/test_stats.py"):
            if path not in files:
                return Decision("read", {"path": path})
        source = files["stats.py"]
        # Explicit heuristic, NOT a general code correctness proof.
        has_guard = "if values else 0.0" in source
        return Decision(final="APPROVED: empty-input guard found" if has_guard else
                        "CHANGES_REQUESTED: empty input can divide by zero; add a guard")


class RoutedModel:
    """V10: failure-aware routing between two offline policies, not paid models."""
    name = "offline-router"

    def __init__(self):
        self.fast = DemoModel(mistake_once=True)
        self.strong = DemoModel(mistake_once=False)
        self.last_route = None

    def next(self, context, tools):
        f = context["facts"]
        repair_failed = any(not t["passed"] and t["patches"] > 0 for t in f["tests"])
        review_failed = f["review"] is not None and not f["review"]["approved"]
        self.last_route = "careful" if repair_failed or review_failed else "fast"
        model = self.strong if self.last_route == "careful" else self.fast
        return model.next(context, tools)
