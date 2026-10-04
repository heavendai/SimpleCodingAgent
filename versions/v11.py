"""V11: mandatory sandbox for repository execution; no host fallback."""
from .v10 import build as previous
from simple_agent.execution import BubblewrapExecutor

TITLE = "执行沙箱与拒绝降级"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    executor = BubblewrapExecutor()
    agent.workspace.executor = executor
    agent.required_execution_backend = executor.name
    agent.preflight = executor.preflight
    # The registered bound Workspace method now dispatches through this backend.
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=11)
