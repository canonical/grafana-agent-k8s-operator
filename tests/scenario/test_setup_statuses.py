# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from typing import Type
from unittest.mock import patch

import grafana_agent
import k8s_charm
import machine_charm
import pytest
from ops import BlockedStatus, UnknownStatus, WaitingStatus, pebble
from ops.testing import CharmType
from scenario import Container, ExecOutput, State, trigger

from tests.scenario.helpers import get_charm_meta


@pytest.fixture(params=["k8s", "lxd"])
def substrate(request):
    return request.param


@pytest.fixture
def charm_type(substrate) -> Type[CharmType]:
    return {"lxd": machine_charm.GrafanaAgentMachineCharm, "k8s": k8s_charm.GrafanaAgentK8sCharm}[
        substrate
    ]


@pytest.fixture
def mock_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@dataclasses.dataclass
class _MockProc:
    returncode: int = 0
    stdout = ""


def _subp_run_mock(*a, **kw):
    return _MockProc(0)


@pytest.fixture(autouse=True)
def patch_all(substrate, mock_cfg_path):
    if substrate == "lxd":
        grafana_agent.CONFIG_PATH = mock_cfg_path
        with patch("subprocess.run", _subp_run_mock):
            yield

    else:
        with patch("k8s_charm.KubernetesServicePatch", lambda x, y: None):
            yield


def test_install(charm_type, substrate, vroot):
    out = trigger(
        state=State(),
        event="install",
        charm_type=charm_type,
        meta=get_charm_meta(charm_type),
        charm_root=vroot,
    )

    if substrate == "lxd":
        assert out.status.unit == ("maintenance", "Installing grafana-agent snap")

    else:
        assert out.status.unit == ("unknown", "")


def test_start(charm_type, substrate, vroot):
    out = trigger(
        state=State(),
        event="start",
        charm_type=charm_type,
        meta=get_charm_meta(charm_type),
        charm_root=vroot,
    )

    if substrate == "lxd":
        assert not grafana_agent.CONFIG_PATH.exists(), "config file written on start"
        assert out.status.unit == WaitingStatus("waiting for agent to start")

    else:
        assert out.status.unit == UnknownStatus()


def test_k8s_charm_start_with_container(charm_type, substrate, vroot):
    if substrate == "lxd":
        pytest.skip("k8s-only test")

    agent = Container(
        name="agent",
        can_connect=True,
        exec_mock={("/bin/agent", "-version"): ExecOutput(stdout="42.42")},
    )

    out = trigger(
        state=State(containers=[agent]),
        event=agent.pebble_ready_event,
        charm_type=charm_type,
        meta=get_charm_meta(charm_type),
        charm_root=vroot,
    )

    assert out.status.unit == BlockedStatus("Missing incoming ('requires') relation")
    agent_out = out.get_container("agent")
    assert agent_out.services["agent"].current == pebble.ServiceStatus.ACTIVE
