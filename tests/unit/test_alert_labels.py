# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from typing import Dict, Union

from helpers import k8s_resource_multipatch, patch_lightkube_client
from ops.testing import Container, PeerRelation, Relation, State

ConfigDict = Dict[str, Union[str, int, float, bool]]

zinc_alerts = {
    "alert_rules": json.dumps(
        {
            "groups": [
                {
                    "name": "alertgroup",
                    "rules": [
                        {
                            "alert": "Missing",
                            "expr": "up == 0",
                            "for": "0m",
                            "labels": {
                                "juju_model": "my_model",
                                "juju_model_uuid": "74a5690b-89c9-44dd-984b-f69f26a6b751",
                                "juju_application": "zinc",
                                "juju_charm": "zinc-k8s",
                            },
                        }
                    ],
                }
            ]
        }
    )
}

containers = [Container(name="agent", can_connect=True)]


@patch_lightkube_client
@k8s_resource_multipatch
def test_extra_alerts_config(ctx):
    # GIVEN a new key-value pair of extra alerts labels, for instance:
    # juju config agent extra_alerts_labels="environment: PRODUCTION, zone=Mars"
    config1: ConfigDict = {
        "extra_alert_labels": "environment: PRODUCTION, zone=Mars",
    }

    # THEN The extra_alert_labels MUST be added to the alert rules.
    metrics_endpoint_relation = Relation(
        "metrics-endpoint", remote_app_name="zinc", remote_app_data=zinc_alerts
    )
    remote_write_relation = Relation("send-remote-write", remote_app_name="prometheus")
    state = State(
        leader=True,
        relations=[
            metrics_endpoint_relation,
            remote_write_relation,
            PeerRelation("peers"),
        ],
        containers=containers,
        config=config1,  # type: ignore
    )
    out_0 = ctx.run(ctx.on.relation_changed(relation=metrics_endpoint_relation), state)
    out_1 = ctx.run(
        ctx.on.relation_joined(relation=out_0.get_relation(remote_write_relation.id)), out_0
    )
    alert_rules = json.loads(
        out_1.get_relation(remote_write_relation.id).local_app_data["alert_rules"]
    )

    for group in alert_rules["groups"]:
        for rule in group["rules"]:
            assert rule["labels"]["environment"] == "PRODUCTION"
            assert rule["labels"]["zone"] == "Mars"
            if "grafana_agent_k8s_alertgroup_alerts" in group["name"]:
                assert rule["labels"]["juju_application"] == "zinc"
                assert rule["labels"]["juju_charm"] == "zinc-k8s"
                assert rule["labels"]["juju_model"] == "my_model"
                assert rule["labels"]["juju_model_uuid"] == "74a5690b-89c9-44dd-984b-f69f26a6b751"

    # GIVEN the config option for extra alert labels is unset
    config2: ConfigDict = {"extra_alert_labels": ""}

    # THEN the only labels present in the alert are the JujuTopology labels
    next_state = State(
        leader=True,
        relations=out_1.relations,
        containers=out_1.containers,
        config=config2,
    )
    out_2 = ctx.run(ctx.on.config_changed(), next_state)
    alert_rules_mod = json.loads(
        out_2.get_relation(remote_write_relation.id).local_app_data["alert_rules"]
    )

    for group in alert_rules_mod["groups"]:
        for rule in group["rules"]:
            assert "environment" not in rule["labels"].keys()
            assert "zone" not in rule["labels"].keys()
            if "grafana_agent_k8s_alertgroup_alerts" in group["name"]:
                assert rule["labels"]["juju_application"] == "zinc"
                assert rule["labels"]["juju_charm"] == "zinc-k8s"
                assert rule["labels"]["juju_model"] == "my_model"
                assert rule["labels"]["juju_model_uuid"] == "74a5690b-89c9-44dd-984b-f69f26a6b751"


@patch_lightkube_client
@k8s_resource_multipatch
def test_extra_loki_alerts_config(ctx):
    # GIVEN a new key-value pair of extra alerts labels, for instance:
    # juju config agent extra_alerts_labels="environment: PRODUCTION, zone=Mars"
    config1: ConfigDict = {
        "extra_alert_labels": "environment: PRODUCTION, zone=Mars",
    }

    # THEN The extra_alert_labels MUST be added to the alert rules.
    logging_provider_relation = Relation(
        "logging-provider", remote_app_name="zinc", remote_app_data=zinc_alerts
    )
    logging_consumer_relation = Relation("logging-consumer", remote_app_name="loki")
    state = State(
        leader=True,
        relations=[
            logging_provider_relation,
            logging_consumer_relation,
            PeerRelation("peers"),
        ],
        containers=containers,
        config=config1,  # type: ignore
    )
    out_0 = ctx.run(ctx.on.relation_changed(relation=logging_provider_relation), state)
    out_1 = ctx.run(
        ctx.on.relation_joined(relation=out_0.get_relation(logging_consumer_relation.id)), out_0
    )
    alert_rules = json.loads(
        out_1.get_relation(logging_consumer_relation.id).local_app_data["alert_rules"]
    )

    for group in alert_rules["groups"]:
        for rule in group["rules"]:
            assert rule["labels"]["environment"] == "PRODUCTION"
            assert rule["labels"]["zone"] == "Mars"
            if "grafana_agent_k8s_alertgroup_alerts" in group["name"]:
                assert rule["labels"]["juju_application"] == "zinc"
                assert rule["labels"]["juju_charm"] == "zinc-k8s"
                assert rule["labels"]["juju_model"] == "my_model"
                assert rule["labels"]["juju_model_uuid"] == "74a5690b-89c9-44dd-984b-f69f26a6b751"

    # GIVEN the config option for extra alert labels is unset
    config2: ConfigDict = {"extra_alert_labels": ""}

    # THEN the only labels present in the alert are the JujuTopology labels
    next_state = State(
        leader=True,
        relations=out_1.relations,
        containers=out_1.containers,
        config=config2,
    )
    out_2 = ctx.run(ctx.on.config_changed(), next_state)
    alert_rules_mod = json.loads(
        out_2.get_relation(logging_consumer_relation.id).local_app_data["alert_rules"]
    )

    for group in alert_rules_mod["groups"]:
        for rule in group["rules"]:
            assert "environment" not in rule["labels"].keys()
            assert "zone" not in rule["labels"].keys()
            if "grafana_agent_k8s_alertgroup_alerts" in group["name"]:
                assert rule["labels"]["juju_application"] == "zinc"
                assert rule["labels"]["juju_charm"] == "zinc-k8s"
                assert rule["labels"]["juju_model"] == "my_model"
                assert rule["labels"]["juju_model_uuid"] == "74a5690b-89c9-44dd-984b-f69f26a6b751"
