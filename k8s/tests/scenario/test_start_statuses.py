# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import inspect
import shutil
from pathlib import Path
from typing import Type
from unittest.mock import patch

import pytest
import yaml
from ops import pebble
from ops.testing import CharmType
from scenario import Container, ExecOutput, State, SubordinateRelation

import charm

CHARM_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def charm_type() -> Type[CharmType]:
    return charm.GrafanaAgentK8sCharm


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
def patch_all(placeholder_cfg_path):
    with patch("charm.KubernetesServicePatch", lambda x, y: None):
        yield


@pytest.fixture
def vroot(tmp_path) -> Path:
    shutil.copytree(CHARM_ROOT / "src", tmp_path / "src")
    return tmp_path


@pytest.fixture
def charm_meta(charm_type) -> dict:
    fname = "metadata"

    charm_source_path = Path(inspect.getfile(charm_type))
    charm_root = charm_source_path.parent.parent

    raw_meta = (charm_root / fname).with_suffix(".yaml").read_text()
    return yaml.safe_load(raw_meta)


def test_install(charm_type, charm_meta, vroot):
    out = State().trigger(
        "install",
        charm_type=charm_type,
        meta=charm_meta,
        charm_root=vroot,
    )
    assert out.status.unit == ("unknown", "")


def test_start(charm_type, charm_meta, vroot, placeholder_cfg_path):
    out = State().trigger(
        "start",
        charm_type=charm_type,
        meta=charm_meta,
        charm_root=vroot,
    )
    assert out.status.unit == ("unknown", "")


def test_k8s_charm_start_with_container(charm_type, charm_meta, vroot):
    agent = Container(
        name="agent",
        can_connect=True,
        exec_mock={("/bin/agent", "-version"): ExecOutput(stdout="42.42")},
    )

    out = State(containers=[agent]).trigger(
        agent.pebble_ready_event,
        charm_type=charm_type,
        meta=charm_meta,
        charm_root=vroot,
    )

    assert out.status.unit == ("active", "")
    agent_out = out.get_container("agent")
    assert agent_out.services["agent"].current == pebble.ServiceStatus.ACTIVE
