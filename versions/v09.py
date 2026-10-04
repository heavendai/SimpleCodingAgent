"""V09: a separate read-only reviewer context; only the worker writes."""
from .v08 import build as previous
from simple_agent.runtime import review

TITLE = "角色协作"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.register("delegate_review", lambda: review(agent))
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=9)
