"""V07: explicit plan plus a deliberately incomplete first fix and repair."""
from .v06 import build as previous
from simple_agent.models import DemoModel
from simple_agent.runtime import set_plan

TITLE = "计划与迭代修复"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.model = DemoModel(mistake_once=True)
    agent.register("set_plan", set_plan)
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=7)
