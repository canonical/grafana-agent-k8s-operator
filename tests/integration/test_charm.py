#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import sh
import yaml
from helpers import get_podspec
from lightkube.utils.quantity import equals_canonically

# pyright: reportAttributeAccessIssue = false

logger = logging.getLogger(__name__)
METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())

default_limits = None
default_requests = {"cpu": "0.25", "memory": "200Mi"}

@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, grafana_agent_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    resources = {"agent-image": METADATA["resources"]["agent-image"]["upstream-source"]}
    resources_arg = f"agent-image={resources['agent-image']}"
    sh.juju.deploy(grafana_agent_charm, "agent", model=ops_test.model.name, resource=resources_arg, trust=True)

    await ops_test.model.wait_for_idle(
        apps=["agent"], status="blocked", timeout=300, idle_period=30
    )
    assert ops_test.model.applications["agent"].units[0].workload_status == "blocked"


async def test_config_cpu_memory(ops_test):
    assert ops_test.model
    await ops_test.model.applications["agent"].reset_config(["cpu", "memory"])
    await ops_test.model.wait_for_idle(timeout=300)

    podspec = get_podspec(ops_test, "agent", "agent")
    assert podspec.resources
    assert equals_canonically(podspec.resources.limits, default_limits)
    assert equals_canonically(podspec.resources.requests, default_requests)


async def test_relates_to_loki(ops_test):
    sh.juju.deploy("loki-k8s", "loki", model=ops_test.model.name, channel="edge", trust=True)
    sh.juju.relate("loki", "agent:logging-consumer", model=ops_test.model.name)

    await ops_test.model.wait_for_idle(
        apps=["agent"],
        status="blocked",
        timeout=300,  # Missing incoming ('requires') relation
    )
    await ops_test.model.wait_for_idle(apps=["loki"], status="active", timeout=300)
