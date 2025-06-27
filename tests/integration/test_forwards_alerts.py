#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import sh
import yaml
from helpers import loki_rules, oci_image, prometheus_rules

# pyright: reportAttributeAccessIssue = false

logger = logging.getLogger(__name__)
METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())

agent_name = "agent"
loki_name = "loki"
loki_tester_name = "loki-tester"
prometheus_name = "prometheus"
prometheus_tester_name = "prometheus-tester"


@pytest.mark.abort_on_fail
async def test_deploy(ops_test, grafana_agent_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {"agent-image": METADATA["resources"]["agent-image"]["upstream-source"]}
    resources_arg = f"agent-image={resources['agent-image']}"
    sh.juju.deploy(
        grafana_agent_charm, agent_name, model=ops_test.model.name, resource=resources_arg
    )

    # due to a juju bug, occasionally some charms finish a startup sequence with "waiting for IP
    # address"
    # issuing placeholder update_status just to trigger an event
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})

    await ops_test.model.wait_for_idle(apps=[agent_name], status="blocked", timeout=300)
    assert ops_test.model.applications[agent_name].units[0].workload_status == "blocked"


async def test_relate_to_external_apps(ops_test):
    sh.juju.deploy("loki-k8s", loki_name, model=ops_test.model.name, channel="1/edge", trust=True)
    sh.juju.deploy(
        "prometheus-k8s",
        prometheus_name,
        model=ops_test.model.name,
        channel="1/edge",
        trust=True,
    )
    sh.juju.relate(f"{loki_name}:logging", agent_name, model=ops_test.model.name)
    sh.juju.relate(
        f"{prometheus_name}:receive-remote-write",
        agent_name,
        model=ops_test.model.name,
    )

    await ops_test.model.wait_for_idle(
        apps=[loki_name, prometheus_name], status="active", timeout=300
    )
    await ops_test.model.wait_for_idle(
        apps=[agent_name],
        status="blocked",
        timeout=300,  # Missing incoming ('requires') relation
    )


async def test_relate_to_loki_tester_and_check_alerts(ops_test, loki_tester_charm):
    sh.juju.deploy(loki_tester_charm, loki_tester_name, model=ops_test.model.name)
    sh.juju.relate(agent_name, loki_tester_name, model=ops_test.model.name)
    await ops_test.model.wait_for_idle(
        apps=[loki_tester_name, agent_name], status="active", timeout=300
    )

    loki_alerts = await loki_rules(ops_test, loki_name)
    assert len(loki_alerts) == 1


async def test_relate_to_prometheus_tester_and_check_alerts(ops_test, prometheus_tester_charm):
    sh.juju.deploy(
        prometheus_tester_charm,
        prometheus_tester_name,
        model=ops_test.model.name,
        resource=f"prometheus-tester-image={oci_image('./tests/integration/prometheus-tester/metadata.yaml', 'prometheus-tester-image')}",
    )
    sh.juju.relate(agent_name, prometheus_tester_name, model=ops_test.model.name)
    await ops_test.model.wait_for_idle(
        apps=[prometheus_tester_name, agent_name], status="active", timeout=300
    )

    prometheus_alerts = await prometheus_rules(ops_test, prometheus_name, 0)
    assert len(prometheus_alerts) > 0
