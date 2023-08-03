# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import inspect
from pathlib import Path
from typing import Type
from unittest.mock import patch

import k8s_charm
import machine_charm
import pytest
import yaml
from ops import pebble
from ops.testing import CharmType
from scenario import Container, Context, ExecOutput, State, SubordinateRelation

CHARM_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(params=["k8s", "lxd"])
def substrate(request):
    return request.param


@pytest.fixture
def charm_type(substrate) -> Type[CharmType]:
    return {"lxd": machine_charm.GrafanaAgentMachineCharm, "k8s": k8s_charm.GrafanaAgentK8sCharm}[
        substrate
    ]


@pytest.fixture
def placeholder_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@dataclasses.dataclass
class _MockProc:
    returncode: int = 0
    stdout: str = ""


def _subp_run_mock(*a, **kw):
    return _MockProc(0)


@pytest.fixture(autouse=True)
def patch_all(substrate, placeholder_cfg_path):
    if substrate == "lxd":
        with patch("subprocess.run", _subp_run_mock), patch(
            "grafana_agent.CONFIG_PATH", placeholder_cfg_path
        ):
            yield

    else:
        with patch("k8s_charm.KubernetesServicePatch", lambda x, y: None):
            yield


@pytest.fixture
def charm_meta(substrate, charm_type) -> dict:
    fname = {"lxd": "machine_metadata", "k8s": "k8s_metadata"}[substrate]

    charm_source_path = Path(inspect.getfile(charm_type))
    charm_root = charm_source_path.parent.parent

    raw_meta = (charm_root / fname).with_suffix(".yaml").read_text()
    return yaml.safe_load(raw_meta)


def test_install(charm_type, charm_meta, substrate, vroot):
    ctx = Context(
        charm_type=charm_type,
        meta=charm_meta,
        charm_root=vroot,
    )
    out = ctx.run(state=State(), event="install")

    if substrate == "lxd":
        assert out.unit_status == ("maintenance", "Installing grafana-agent snap")

    else:
        assert out.unit_status == ("unknown", "")


def test_start_not_ready(charm_type, charm_meta, substrate, vroot, placeholder_cfg_path):
    if substrate != "lxd":
        pytest.skip(reason="machine-only test")

    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert not charm.is_ready

    juju_info = SubordinateRelation("juju-info")
    with patch("machine_charm.GrafanaAgentMachineCharm.is_ready", False):
        ctx = Context(
            charm_type=charm_type,
            meta=charm_meta,
            charm_root=vroot,
        )
        out = ctx.run(
            state=State(relations=[juju_info]), event=juju_info.joined_event, post_event=post_event
        )

    assert out.unit_status == ("waiting", "waiting for agent to start")


def test_start(charm_type, charm_meta, substrate, vroot, placeholder_cfg_path):
    with patch("machine_charm.GrafanaAgentMachineCharm.is_ready", True):
        ctx = Context(
            charm_type=charm_type,
            meta=charm_meta,
            charm_root=vroot,
        )
        out = ctx.run(state=State(), event="start")

    if substrate == "lxd":
        written_cfg = placeholder_cfg_path.read_text()
        assert written_cfg  # check nonempty

        assert out.unit_status.name == "blocked"

    else:
        assert out.unit_status.name == "unknown"


def test_k8s_charm_start_with_container(charm_type, charm_meta, substrate, vroot):
    if substrate == "lxd":
        pytest.skip("k8s-only test")

    agent = Container(
        name="agent",
        can_connect=True,
        exec_mock={("/bin/agent", "-version"): ExecOutput(stdout="42.42")},
    )

    ctx = Context(
        charm_type=charm_type,
        meta=charm_meta,
        charm_root=vroot,
    )
    out = ctx.run(state=State(containers=[agent]), event=agent.pebble_ready_event)

    assert out.unit_status.name == "blocked"
    agent_out = out.get_container("agent")
    assert agent_out.services["agent"].current == pebble.ServiceStatus.ACTIVE
