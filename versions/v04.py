"""V04: run real trusted-fixture tests; completion needs fresh evidence."""
from .v03 import build as previous

TITLE = "执行与验证"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.register("run_tests", agent.workspace.run_tests)
    agent.require_verified = True
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=4)
