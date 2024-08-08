# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch, MagicMock

import pytest
from ops import BlockedStatus, UnknownStatus, pebble
from scenario import Container, Context, ExecOutput, State

import charm
import grafana_agent


@pytest.fixture
def mock_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@pytest.fixture(autouse=True)
def patch_all(mock_cfg_path):
    grafana_agent.CONFIG_PATH = mock_cfg_path

    procmock = MagicMock()
    procmock.returncode = 0
    procmock.stdout = ""

    with patch("subprocess.run", new_callable=lambda: procmock):
        yield


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
