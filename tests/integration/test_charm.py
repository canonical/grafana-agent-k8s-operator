#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import pytest
import yaml
from pathlib import Path

log = logging.getLogger(__name__)
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
