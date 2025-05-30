from helpers import k8s_resource_multipatch, patch_lightkube_client
from ops.testing import Container, State

containers = [Container(name="agent", can_connect=True)]


@patch_lightkube_client
@k8s_resource_multipatch
def test_reporting_enabled(ctx):
    # GIVEN the "reporting_enabled" config option is set to True
    state = State(leader=True, config={"reporting_enabled": True}, containers=containers)

    # WHEN config-changed fires
    out = ctx.run(ctx.on.config_changed(), state)

    # THEN the service layer does NOT include the "-disable-reporting" arg
    assert (
        "-disable-reporting"
        not in out.get_container("agent").layers["agent"].services["agent"].command
    )


@patch_lightkube_client
@k8s_resource_multipatch
def test_reporting_disabled(ctx):
    # GIVEN the "reporting_enabled" config option is set to False
    state = State(leader=True, config={"reporting_enabled": False}, containers=containers)
    # WHEN config-changed fires
    out = ctx.run(ctx.on.config_changed(), state)

    # THEN the service layer INCLUDES the "-disable-reporting" arg
    assert (
        "-disable-reporting"
        in out.get_container("agent").layers["agent"].services["agent"].command
    )
