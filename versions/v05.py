"""V05: host-owned write approval. Path containment already exists in V02."""
from .v04 import build as previous
from simple_agent.policy import Policy

TITLE = "权限与边界"


def build(root, require_approval=False, **kwargs):
    agent = previous(root, **kwargs)
    agent.policy = Policy(can_write=not require_approval)
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=5)
