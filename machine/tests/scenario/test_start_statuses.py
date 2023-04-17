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
from ops.testing import CharmType
from scenario import State, SubordinateRelation

import charm

CHARM_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def charm_type() -> Type[CharmType]:
    return charm.GrafanaAgentMachineCharm


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
    with patch("subprocess.run", _subp_run_mock):
        with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
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
    assert out.status.unit == ("maintenance", "Installing grafana-agent snap")


def test_start_not_ready(charm_type, charm_meta, vroot, placeholder_cfg_path):
    def post_event(charm: charm.GrafanaAgentMachineCharm):
        assert not charm.is_ready

    juju_info = SubordinateRelation("juju-info")
    with patch("charm.GrafanaAgentMachineCharm.is_ready", False):
        out = State(relations=[juju_info]).trigger(
            juju_info.joined_event,
            charm_type=charm_type,
            meta=charm_meta,
            charm_root=vroot,
            post_event=post_event,
        )

    assert out.status.unit == ("waiting", "waiting for agent to start")


def test_start(charm_type, charm_meta, vroot, placeholder_cfg_path):
    with patch("charm.GrafanaAgentMachineCharm.is_ready", True):
        out = State().trigger(
            "start",
            charm_type=charm_type,
            meta=charm_meta,
            charm_root=vroot,
        )
    written_cfg = placeholder_cfg_path.read_text()
    assert written_cfg  # check nonempty
    assert out.status.unit == ("active", "")
