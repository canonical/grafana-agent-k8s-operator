# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import yaml
from ops.testing import Container, Context, Relation, State

from charm import GrafanaAgentK8sCharm
from grafana_agent import CONFIG_PATH


def test_prometheus_endpoints_deduplication():
    # GIVEN a set of duplicate Prometheus endpoints
    remote_write_url = "http://traefik.ip/cos-mimir/api/v1/push"
    mimir_relation = Relation(
        "send-remote-write",
        remote_units_data={
            0: {"remote_write": json.dumps({"url": remote_write_url})},
            1: {"remote_write": json.dumps({"url": remote_write_url})},
            2: {"remote_write": json.dumps({"url": remote_write_url})},
        },
    )
    state = State(
        leader=True,
        containers={Container(name="agent", can_connect=True)},
        relations=[
            mimir_relation,
        ],
        config={
            "forward_alert_rules": True,
        },
    )

    # WHEN the charm processes endpoints with duplicates
    ctx = Context(charm_type=GrafanaAgentK8sCharm)

    with ctx(ctx.on.config_changed(), state) as mgr:
        output_state = mgr.run()
        agent = output_state.get_container("agent")

        # THEN the agent has started
        assert agent.services["agent"].is_running()
        # AND the grafana agent config has deduplicated the endpoints
        fs = agent.get_filesystem(ctx)
        gagent_config = fs.joinpath(*CONFIG_PATH.strip("/").split("/"))
        assert gagent_config.exists()
        yml = yaml.safe_load(gagent_config.read_text())
        # check endpoints are deduplicated in the metrics section
        metrics_config = yml["metrics"]["configs"][0]
        assert metrics_config["name"] == "agent_scraper"
        assert len(metrics_config["remote_write"]) == 1
        assert metrics_config["remote_write"][0]["url"] == remote_write_url
        # check endpoints are deduplicated in the integrations section
        integrations_config = yml["integrations"]
        assert len(integrations_config["prometheus_remote_write"]) == 1
        assert integrations_config["prometheus_remote_write"][0]["url"] == remote_write_url
