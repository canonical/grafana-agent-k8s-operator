# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
async def charm_under_test(ops_test: OpsTest):
    """Charm used for integration testing."""
    charm = await ops_test.build_charm(".")
    return charm
