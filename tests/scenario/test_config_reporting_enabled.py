from ops.testing import State, Container
from configparser import ConfigParser


containers = [Container(name="agent", can_connect=True)]


def test_reporting_enabled(ctx):
    # GIVEN the "reporting_enabled" config option is set to True
    state = State(
        leader=True, config={"reporting_enabled": True}, containers=containers
    )

    # WHEN config-changed fires
    out = ctx.run(ctx.on.config_changed(), state)

    # THEN the service layer does NOT include the "-disable-reporting" arg
    assert "-disable-reporting" not in out.get_container("agent").layers.services["agent"].to_dict().command


def test_reporting_disabled(ctx):
    # GIVEN the "reporting_enabled" config option is set to False
    state = State(leader=True, config={"reporting_enabled": False}, containers=containers)
    # WHEN config-changed fires
    out = ctx.run(ctx.on.config_changed(), state)

    # THEN the service layer INCLUDES the "-disable-reporting" arg
    assert "-disable-reporting" in out.get_container("agent").layers.services["agent"].to_dict().command
