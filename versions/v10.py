"""V10: routed model, shared budgets, durable traces and external evals."""
from .v09 import build as previous
from simple_agent.models import RoutedModel
from simple_agent.runtime import Budget

TITLE = "预算路由追踪评测"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.model = RoutedModel()
    agent.budget = Budget(max_calls=35, max_tool_calls=32, max_model_chars=180_000)
    agent.trace_path = root.parent / "trace.jsonl"
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=10)
