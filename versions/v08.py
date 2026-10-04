"""V08: atomic checkpoints, fingerprint-checked continuation, no fake rollback."""
from .v07 import build as previous

TITLE = "检查点与恢复"


def build(root, **kwargs):
    agent = previous(root, **kwargs)
    agent.checkpoint_path = root.parent / "checkpoint.json"
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=8)
