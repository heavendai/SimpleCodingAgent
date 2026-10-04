"""V06: repo guidance, bounded retrieval, structured facts and compaction."""
from .v05 import build as previous
from simple_agent.runtime import repo_context, load_skill

TITLE = "仓库上下文"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.register("repo_context", lambda: repo_context(agent.workspace))
    agent.register("load_skill", lambda name: load_skill(agent.workspace, name))
    agent.compaction = True
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=6)
