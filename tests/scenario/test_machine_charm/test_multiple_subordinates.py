# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import charm
import pytest
from charms.grafana_agent.v0.cos_agent import MultiplePrincipalsError
from scenario import Context, PeerRelation, State, SubordinateRelation

from tests.scenario.helpers import get_charm_meta


def test_juju_info_and_cos_agent(vroot):
    def post_event(charm: charm.GrafanaAgentMachineCharm):
        assert len(charm._cos.dashboards) == 1
        assert len(charm._cos.snap_log_endpoints) == 1
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert len(charm._cos.metrics_jobs) == 1
        assert charm._principal_relation.name == "juju-info"

    cos_agent_data = {
        "config": json.dumps(
            {
                "subordinate": True,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "hardware-observer_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["foo:bar"],
            }
        )
    }

    cos_agent_relation = SubordinateRelation(
        "cos-agent", remote_app_name="hardware-observer", remote_unit_data=cos_agent_data
    )

    context = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
        meta=get_charm_meta(charm.GrafanaAgentMachineCharm),
        charm_root=vroot,
    )
    state = State(
        relations=[
            cos_agent_relation,
            SubordinateRelation("juju-info", remote_app_name="remote-juju-info"),
            PeerRelation("peers"),
        ]
    )
    context.run(event=cos_agent_relation.changed_event, state=state, post_event=post_event)


def test_two_cos_agent_relations(vroot):
    def post_event(charm: charm.GrafanaAgentMachineCharm):
        assert len(charm._cos.dashboards) == 2
        assert len(charm._cos.snap_log_endpoints) == 2
        assert not charm._cos.logs_alerts
        assert not charm._cos.metrics_alerts
        assert len(charm._cos.metrics_jobs) == 2
        assert charm._principal_relation.name == "cos-agent"
        assert charm._principal_relation.app.name == "primary"

    cos_agent_primary_data = {
        "config": json.dumps(
            {
                "subordinate": False,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "primary_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["foo:bar"],
            }
        )
    }

    cos_agent_subordinate_data = {
        "config": json.dumps(
            {
                "subordinate": True,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "subordinate_0", "path": "/metrics", "port": "8081"}
                ],
                "log_slots": ["oh:snap"],
            }
        )
    }

    cos_agent_primary_relation = SubordinateRelation(
        "cos-agent", remote_app_name="primary", remote_unit_data=cos_agent_primary_data
    )
    cos_agent_subordinate_relation = SubordinateRelation(
        "cos-agent", remote_app_name="subordinate", remote_unit_data=cos_agent_subordinate_data
    )

    context = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
        meta=get_charm_meta(charm.GrafanaAgentMachineCharm),
        charm_root=vroot,
    )
    state = State(
        relations=[
            cos_agent_primary_relation,
            cos_agent_subordinate_relation,
            PeerRelation("peers"),
        ]
    )
    out_state = context.run(event=cos_agent_primary_relation.changed_event, state=state)
    vroot.clean()
    context.run(
        event=cos_agent_subordinate_relation.changed_event, state=out_state, post_event=post_event
    )


def test_two_cos_primary_relations(vroot):
    def post_event(charm: charm.GrafanaAgentMachineCharm):
        with pytest.raises(MultiplePrincipalsError):
            charm._principal_relation

    cos_agent_primary_data = {
        "config": json.dumps(
            {
                "subordinate": False,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "primary_0", "path": "/metrics", "port": "8080"}
                ],
                "log_slots": ["foo:bar"],
            }
        )
    }

    cos_agent_subordinate_data = {
        "config": json.dumps(
            {
                "subordinate": False,
                "metrics_alert_rules": {},
                "log_alert_rules": {},
                "dashboards": [
                    "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
                    "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
                ],
                "metrics_scrape_jobs": [
                    {"job_name": "subordinate_0", "path": "/metrics", "port": "8081"}
                ],
                "log_slots": ["oh:snap"],
            }
        )
    }

    cos_agent_primary_relation = SubordinateRelation(
        "cos-agent", remote_app_name="primary", remote_unit_data=cos_agent_primary_data
    )
    cos_agent_subordinate_relation = SubordinateRelation(
        "cos-agent", remote_app_name="subordinate", remote_unit_data=cos_agent_subordinate_data
    )

    context = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
        meta=get_charm_meta(charm.GrafanaAgentMachineCharm),
        charm_root=vroot,
    )
    state = State(
        relations=[
            cos_agent_primary_relation,
            cos_agent_subordinate_relation,
            PeerRelation("peers"),
        ]
    )
    context.run(
        event=cos_agent_subordinate_relation.changed_event, state=state, post_event=post_event
    )
