# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from ops import BlockedStatus, UnknownStatus, pebble
from scenario import Container, Context, ExecOutput, State

import charm


def test_install(vroot):
    context = Context(
        charm.GrafanaAgentK8sCharm,
        charm_root=vroot,
    )
    out = context.run("install", State())
    assert out.unit_status == UnknownStatus()


def test_start(vroot):
    context = Context(
        charm.GrafanaAgentK8sCharm,
        charm_root=vroot,
    )
    out = context.run("start", State())
    assert out.unit_status == UnknownStatus()


def test_charm_start_with_container(vroot):
    agent = Container(
        name="agent",
        can_connect=True,
        exec_mock={("/bin/agent", "-version"): ExecOutput(stdout="42.42")},
    )

    context = Context(
        charm.GrafanaAgentK8sCharm,
        charm_root=vroot,
    )
    state = State(containers=[agent])
    out = context.run(agent.pebble_ready_event, state)

    assert out.unit_status == BlockedStatus(
        "Missing incoming ('requires') relation: metrics-endpoint|logging-provider|tracing-provider|grafana-dashboards-consumer"
    )
    agent_out = out.get_container("agent")
    assert agent_out.services["agent"].current == pebble.ServiceStatus.ACTIVE
