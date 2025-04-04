# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from ops import BlockedStatus, UnknownStatus, pebble
from ops.testing import Container, Exec, State


def test_install(ctx):
    out = ctx.run(ctx.on.install(), State())
    assert out.unit_status == UnknownStatus()


def test_start(ctx):
    out = ctx.run(ctx.on.start(), State())
    assert out.unit_status == UnknownStatus()


def test_charm_start_with_container(ctx):
    agent = Container(
        name="agent",
        can_connect=True,
        execs={Exec(["/bin/agent", "-version"], return_code=0, stdout="42.42")},
    )

    state = State(containers=[agent])
    out = ctx.run(ctx.on.pebble_ready(agent), state)

    assert out.unit_status == BlockedStatus(
        "Missing incoming ('requires') relation: metrics-endpoint|logging-provider|tracing-provider|grafana-dashboards-consumer"
    )
    agent_out = out.get_container("agent")
    assert agent_out.services["agent"].current == pebble.ServiceStatus.ACTIVE
