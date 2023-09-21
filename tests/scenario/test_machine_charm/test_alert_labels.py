# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import charm
from scenario import Context, PeerRelation, Relation, State, SubordinateRelation

from tests.scenario.helpers import get_charm_meta


def test_metrics_alert_rule_labels(vroot):
    """Check that metrics alert rules are labeled with principal topology."""
    cos_agent_primary_data = {
        "config": json.dumps(
            {
                "subordinate": False,
                "metrics_alert_rules": {
                    "groups": [
                        {
                            "name": "alertgroup",
                            "rules": [
                                {
                                    "alert": "Missing",
                                    "expr": "up == 0",
                                    "for": "0m",
                                    "labels": {
                                        "juju_model": "machine",
                                        "juju_model_uuid": "74a5690b-89c9-44dd-984b-f69f26a6b751",
                                        "juju_application": "primary",
                                    },
                                }
                            ],
                        }
                    ]
                },
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
                "metrics_alert_rules": {
                    "groups": [
                        {
                            "name": "alertgroup",
                            "rules": [
                                {
                                    "alert": "Missing",
                                    "expr": "up == 0",
                                    "for": "0m",
                                    "labels": {
                                        "juju_model": "machine",
                                        "juju_model_uuid": "74a5690b-89c9-44dd-984b-f69f26a6b751",
                                        "juju_application": "subordinate",
                                    },
                                }
                            ],
                        }
                    ]
                },
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
    remote_write_relation = Relation("send-remote-write", remote_app_name="prometheus")

    context = Context(
        charm_type=charm.GrafanaAgentMachineCharm,
        meta=get_charm_meta(charm.GrafanaAgentMachineCharm),
        charm_root=vroot,
    )
    state = State(
        leader=True,
        relations=[
            cos_agent_primary_relation,
            cos_agent_subordinate_relation,
            remote_write_relation,
            PeerRelation("peers"),
        ],
    )
    state_0 = context.run(event=cos_agent_primary_relation.changed_event, state=state)
    (vroot / "metadata.yaml").unlink(missing_ok=True)
    (vroot / "config.yaml").unlink(missing_ok=True)
    (vroot / "actions.yaml").unlink(missing_ok=True)
    state_1 = context.run(event=cos_agent_subordinate_relation.changed_event, state=state_0)
    (vroot / "metadata.yaml").unlink(missing_ok=True)
    (vroot / "config.yaml").unlink(missing_ok=True)
    (vroot / "actions.yaml").unlink(missing_ok=True)
    state_2 = context.run(event=remote_write_relation.joined_event, state=state_1)

    alert_rules = json.loads(state_2.relations[2].local_app_data["alert_rules"])
    for group in alert_rules["groups"]:
        for rule in group["rules"]:
            assert rule["labels"]["juju_application"] == "primary"
