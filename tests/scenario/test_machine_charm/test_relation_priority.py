# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from pathlib import Path
from unittest.mock import patch

import grafana_agent
import machine_charm
import pytest
from charms.grafana_agent.v0.cos_machine import COSMachineProvider
from scenario import PeerRelation, State, SubordinateRelation
from scenario import trigger as _trigger

from tests.scenario.helpers import get_charm_meta
from tests.scenario.test_machine_charm.helpers import set_run_out


def trigger(evt: str, state: State, vroot: Path = None, **kwargs):
    return _trigger(
        event=evt,
        state=state,
        charm_type=machine_charm.GrafanaAgentMachineCharm,
        meta=get_charm_meta(machine_charm.GrafanaAgentMachineCharm),
        charm_root=vroot,
        **kwargs,
    )


@pytest.fixture
def mock_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


@pytest.fixture(autouse=True)
def patch_all(mock_cfg_path):
    grafana_agent.CONFIG_PATH = mock_cfg_path
    yield


@patch("machine_charm.subprocess.run")
def test_no_relations(mock_run, vroot):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert not charm._cos.dashboards
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert not charm._cos.metrics_jobs
        assert not charm._cos.snap_log_endpoints

        assert not charm._principal_relation
        assert not charm.principal_unit

    set_run_out(mock_run, 0)
    trigger("start", State(), post_event=post_event, vroot=vroot)


@patch("machine_charm.subprocess.run")
def test_juju_info_relation(mock_run, vroot):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert not charm._cos.dashboards
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert not charm._cos.metrics_jobs
        assert not charm._cos.snap_log_endpoints

        assert charm._principal_relation
        assert charm.principal_unit

    set_run_out(mock_run, 0)
    trigger(
        "start",
        State(relations=[SubordinateRelation("juju-info")]),
        post_event=post_event,
        vroot=vroot,
    )


@patch("machine_charm.subprocess.run")
def test_cos_machine_relation(mock_run, vroot):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert charm._cos.dashboards
        assert charm._cos.snap_log_endpoints
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert charm._cos.metrics_jobs

        assert charm._principal_relation.name == "cos-agent"
        assert charm.principal_unit.name == "mock-principal/0"

    set_run_out(mock_run, 0)

    cos_agent_data = {
        "config": json.dumps(
            {
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "mock-principal_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["charmed-kafka:logs"],
            }
        )
    }

    peer_data = {
        "config": json.dumps(
            {
                "principal_unit_name": "foo",
                "principal_relation_id": "2",
                "principal_relation_name": "peers",
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    COSMachineProvider._encode_dashboard_content('{"very long": "dashboard"}')
                ],
            }
        )
    }
    trigger(
        "start",
        State(
            relations=[
                SubordinateRelation(
                    "cos-agent",
                    remote_app_name="mock-principal",
                    remote_unit_data=cos_agent_data,
                ),
                PeerRelation("peers", peers_data={1: peer_data}),
            ]
        ),
        post_event=post_event,
        vroot=vroot,
    )


@patch("machine_charm.subprocess.run")
def test_both_relations(mock_run, vroot):
    def post_event(charm: machine_charm.GrafanaAgentMachineCharm):
        assert charm._cos.dashboards
        assert not charm._cos.snap_log_endpoints
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert not charm._cos.metrics_jobs

        # we have both, but principal is grabbed from cos-machine
        assert charm._principal_relation.name == "cos-agent"
        assert charm.principal_unit.name == "remote-cos-agent/0"

    set_run_out(mock_run, 0)

    cos_agent_data = {
        "config": json.dumps(
            {
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "mock-principal_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["charmed-kafka:logs"],
            }
        )
    }

    peer_data = {
        "config": json.dumps(
            {
                "principal_unit_name": "foo",
                "principal_relation_id": "2",
                "principal_relation_name": "peers",
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    COSMachineProvider._encode_dashboard_content('{"very long": "dashboard"}')
                ],
            }
        )
    }

    trigger(
        "start",
        State(
            relations=[
                SubordinateRelation(
                    "cos-agent", remote_app_name="remote-cos-agent", remote_app_data=cos_agent_data
                ),
                # SubordinateRelation("juju-info", remote_app_name="remote-juju-info"),
                PeerRelation("peers", peers_data={1: peer_data}),
            ]
        ),
        post_event=post_event,
        vroot=vroot,
    )
