"""V01: model interface only. A suggestion is not a verified code change."""
from simple_agent.models import DemoModel
from simple_agent.protocol import State
from simple_agent.runtime import Engine
from simple_agent.workspace import Workspace

TITLE = "模型接口"


def build(root, **kwargs):
    agent = Engine(Workspace(root), DemoModel(),
                   State("Fix mean(values); empty input must return 0.0"))
    agent.complete_status = "suggested"
    return agent


if __name__ == "__main__":
    from simple_agent.cli import main
    main(default_version=1)
