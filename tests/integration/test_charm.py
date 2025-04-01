#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml

logger = logging.getLogger(__name__)
METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, grafana_agent_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    resources = {"agent-image": METADATA["resources"]["agent-image"]["upstream-source"]}
    await ops_test.model.deploy(grafana_agent_charm, resources=resources, application_name="agent")

    await ops_test.model.wait_for_idle(
        apps=["agent"], status="blocked", timeout=300, idle_period=30
    )
    assert ops_test.model.applications["agent"].units[0].workload_status == "blocked"


async def test_relates_to_loki(ops_test):
    await ops_test.model.deploy("loki-k8s", channel="edge", application_name="loki", trust=True)
    await ops_test.model.add_relation("loki", "agent:logging-consumer")

    await ops_test.model.wait_for_idle(
        apps=["agent"], status="blocked", timeout=300  # Missing incoming ('requires') relation
    )
    await ops_test.model.wait_for_idle(apps=["loki"], status="active", timeout=300)
