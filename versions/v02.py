"""V02: add a genuine observe/act loop through read-only tools."""
from .v01 import build as previous

TITLE = "只读工具与循环"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.register("search", agent.workspace.search)
    agent.register("read", agent.workspace.read)
    agent.complete_status = "inspected"
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=2)
