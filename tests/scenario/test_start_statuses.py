# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import inspect
from pathlib import Path
from typing import Type
from unittest.mock import patch

import charm
import pytest
import yaml
from ops.testing import CharmType
from scenario import Context, State, SubordinateRelation

CHARM_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(params=["k8s", "lxd"])
def substrate(request):
    return request.param


@pytest.fixture
def charm_type(substrate) -> Type[CharmType]:
    return {"lxd": charm.GrafanaAgentMachineCharm}[substrate]


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
    with patch("subprocess.run", _subp_run_mock), patch(
        "grafana_agent.CONFIG_PATH", placeholder_cfg_path
    ):
        yield


@pytest.fixture
def charm_meta(substrate, charm_type) -> dict:
    fname = {"lxd": "metadata"}[substrate]

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

    def post_event(charm: charm.GrafanaAgentMachineCharm):
        assert not charm.is_ready

    juju_info = SubordinateRelation("juju-info")
    with patch("charm.GrafanaAgentMachineCharm.is_ready", False):
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
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
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
