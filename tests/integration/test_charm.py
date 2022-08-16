#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from helpers import (
    get_grafana_dashboards,
    get_prometheus_active_targets,
    get_prometheus_rules,
)

logger = logging.getLogger(__name__)
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, grafana_agent_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    resources = {"agent-image": METADATA["resources"]["agent-image"]["upstream-source"]}
    await ops_test.model.deploy(grafana_agent_charm, resources=resources, application_name="agent")

    await ops_test.model.wait_for_idle(
        apps=["agent"], status="active", timeout=300, idle_period=30
    )
    assert ops_test.model.applications["agent"].units[0].workload_status == "active"


async def test_relates_to_loki(ops_test):
    await ops_test.model.deploy("loki-k8s", channel="edge", application_name="loki", trust=True)
    await ops_test.model.add_relation("loki", "agent:logging-consumer")
    await ops_test.model.wait_for_idle(apps=["loki", "agent"], status="active", timeout=1000)


async def test_has_own_dashboard(ops_test):
    await ops_test.model.deploy("grafana-k8s", channel="edge", application_name="grafana")
    await ops_test.model.add_relation("grafana", "agent:grafana-dashboard")
    await ops_test.model.wait_for_idle(apps=["agent", "grafana"], status="active", timeout=1000)
    dashboards = await get_grafana_dashboards(ops_test, "grafana", 0)
    assert any(dashboard["title"] == "Grafana Agent" for dashboard in dashboards)


async def test_has_own_alert_rules(ops_test):
    await ops_test.model.deploy(
        "prometheus-k8s", channel="edge", application_name="prometheus", trust=True
    )
    await ops_test.model.wait_for_idle(apps=["prometheus"], status="active", timeout=1000)
    alert_rules = await get_prometheus_rules(ops_test, "prometheus", 0)

    # Check we do not have alert rules in Prometheus
    assert len(alert_rules) == 0

    await ops_test.model.add_relation("prometheus", "agent:self-metrics-endpoint")
    await ops_test.model.wait_for_idle(apps=["agent", "prometheus"], status="active", timeout=1000)

    alert_rules = await get_prometheus_rules(ops_test, "prometheus", 0)

    # Check now we have alert rules (provided by Grafana Agent)
    assert len(alert_rules) > 0
    for group in alert_rules:
        assert len(group["rules"]) >= 1

    juju_applications = ["agent", "prometheus"]
    targets = await get_prometheus_active_targets(ops_test, "prometheus", 0)
    assert len(targets) == 2
    for target in targets:
        assert target["labels"]["juju_application"] in juju_applications
