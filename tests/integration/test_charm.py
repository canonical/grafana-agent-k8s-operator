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
async def test_build_and_deploy(ops_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    charm_under_test = await ops_test.build_charm(".")
    resources = {"agent-image": METADATA["resources"]["agent-image"]["upstream-source"]}
    await ops_test.model.deploy(charm_under_test, resources=resources, application_name="agent")

    # due to a juju bug, occasionally some charms finish a startup sequence with "waiting for IP
    # address"
    # issuing dummy update_status just to trigger an event
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})

    await ops_test.model.wait_for_idle(apps=["agent"], status="active", timeout=1000)
    assert ops_test.model.applications["agent"].units[0].workload_status == "active"

    # effectively disable the update status from firing
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})


async def test_relating_to_loki(ops_test):
    await ops_test.model.deploy("loki-k8s", channel="edge", application_name="loki")
    await ops_test.model.add_relation("loki", "agent:logging-consumer")
    await ops_test.model.wait_for_idle(apps=["loki", "agent"], status="active", timeout=1000)


async def test_relating_to_grafana(ops_test):
    await ops_test.model.deploy("grafana-k8s", channel="edge", application_name="grafana")
    await ops_test.model.add_relation("grafana", "agent:grafana-dashboard")
    await ops_test.model.wait_for_idle(apps=["agent", "grafana"], status="active", timeout=1000)
    dashboards = await get_grafana_dashboards(ops_test, "grafana", 0)
    assert dashboards[0]["title"] == "Grafana Agent"


async def test_relating_to_prometheus(ops_test):
    await ops_test.model.deploy(
        "prometheus-k8s", channel="edge", application_name="prometheus", trust=True
    )
    await ops_test.model.add_relation("prometheus", "agent:self-metrics-endpoint")
    await ops_test.model.wait_for_idle(apps=["agent", "prometheus"], status="active", timeout=1000)
    alert_rules_names = [
        "GrafanaAgentRequestErrors",
        "GrafanaAgentRequestLatency",
        "GrafanaAgentUnavailable",
    ]
    alert_rules = await get_prometheus_rules(ops_test, "prometheus", 0)
    assert len(alert_rules) == 3
    for group in alert_rules:
        assert group["rules"][0]["name"] in alert_rules_names

    juju_applications = ["agent", "prometheus"]
    targets = await get_prometheus_active_targets(ops_test, "prometheus", 0)
    assert len(targets) == 2
    for target in targets:
        assert target["labels"]["juju_application"] in juju_applications
