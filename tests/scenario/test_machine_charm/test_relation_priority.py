import base64
import dataclasses
import inspect
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml
from scenario import State, trigger as _trigger, Relation

import grafana_agent
import machine_charm
from charms.grafana_agent.v0.cos_machine import COSMachineProvider
from tests.scenario.helpers import get_charm_meta, CHARM_ROOT
from tests.scenario.test_machine_charm.helpers import set_run_out


def trigger(evt: str, state: State, **kwargs):
    return _trigger(
        event=evt,
        state=state,
        charm_type=machine_charm.GrafanaAgentMachineCharm,
        meta=get_charm_meta(machine_charm.GrafanaAgentMachineCharm),
        copy_to_charm_root={"/src/": CHARM_ROOT / "src"},
        **kwargs
    )


@pytest.fixture
def dummy_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@pytest.fixture(autouse=True)
def patch_all(dummy_cfg_path):
    grafana_agent.CONFIG_PATH = dummy_cfg_path
    yield


@patch("machine_charm.subprocess.run")
def test_no_relations(mock_run):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert not charm._cos.dashboards
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert not charm._cos.metrics_jobs
        assert not charm._cos.snap_log_plugs

        assert not charm._principal_relation
        assert not charm.principal_unit

    set_run_out(mock_run, 0)
    out = trigger("start", State(),
                  post_event=post_event)


@patch("machine_charm.subprocess.run")
def test_juju_info_relation(mock_run):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert not charm._cos.dashboards
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert not charm._cos.metrics_jobs
        assert not charm._cos.snap_log_plugs

        assert charm._principal_relation
        assert charm.principal_unit

    set_run_out(mock_run, 0)
    out = trigger(
        "start",
        State(
            relations=[Relation('juju-info')]
        ),
        post_event=post_event)


@patch("machine_charm.subprocess.run")
def test_cos_machine_relation(mock_run):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert charm._cos.dashboards
        assert charm._cos.snap_log_plugs
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert not charm._cos.metrics_jobs

        assert charm._principal_relation.name == 'cos-machine'
        assert charm.principal_unit.name == 'remote-cos-machine/0'

    set_run_out(mock_run, 0)
    data = {
        'config': json.dumps({
            "metrics": {
                "scrape_jobs": [],
                "alert_rules": {},
            },
            "logs": {
                "targets": ["foo:bar", "baz:qux"],
                "alert_rules": {},
            },
            "dashboards": {
                "dashboards": [
                    COSMachineProvider._encode_dashboard_content("very long dashboard")
                ],
            },
        }
        )
    }
    out = trigger(
        "start",
        State(
            relations=[
                Relation('cos-machine',
                         remote_app_name='remote-cos-machine',
                         remote_app_data=data)
            ]
        ),
        post_event=post_event)


@patch("machine_charm.subprocess.run")
def test_both_relations(mock_run):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert charm._cos.dashboards
        assert charm._cos.snap_log_plugs
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert not charm._cos.metrics_jobs

        # we have both, but principal is grabbed from cos-machine
        assert charm._principal_relation.name == 'cos-machine'
        assert charm.principal_unit.name == 'remote-cos-machine/0'

    set_run_out(mock_run, 0)
    data = {
        'config': json.dumps({
            "metrics": {
                "scrape_jobs": [],
                "alert_rules": {},
            },
            "logs": {
                "targets": ["foo:bar", "baz:qux"],
                "alert_rules": {},
            },
            "dashboards": {
                "dashboards": [
                    COSMachineProvider._encode_dashboard_content("very long dashboard")
                ],
            },
        }
        )
    }
    out = trigger(
        "start",
        State(
            relations=[
                Relation('cos-machine',
                         remote_app_name='remote-cos-machine',
                         remote_app_data=data),
                Relation('juju-info',
                         remote_app_name='remote-juju-info')
            ]
        ),
        post_event=post_event)
