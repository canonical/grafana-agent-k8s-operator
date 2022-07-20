#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_deploy_from_edge_and_upgrade_from_local_path(ops_test, grafana_agent_charm):
    """Deploy from charmhub and then upgrade with the charm-under-test."""
    logger.info("deploy charm from charmhub")
    resources = {"agent-image": METADATA["resources"]["agent-image"]["upstream-source"]}
    await ops_test.model.deploy(f"ch:{app_name}", application_name=app_name, channel="edge")

    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

    logger.info("upgrade deployed charm with local charm %s", grafana_agent_charm)
    await ops_test.model.applications[app_name].refresh(
        path=grafana_agent_charm, resources=resources
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
