"""V03: exact replacement, conflict detection, atomic write, visible diff."""
from .v02 import build as previous

TITLE = "定点补丁"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.register("patch", agent.workspace.patch)
    agent.complete_status = "modified_unverified"
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=3)
