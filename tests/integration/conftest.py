# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import functools
import logging
import os
import shutil
from collections import defaultdict
from datetime import datetime

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


class Store(defaultdict):
    def __init__(self):
        super(Store, self).__init__(Store)

    def __getattr__(self, key):
        """Override __getattr__ so dot syntax works on keys."""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        """Override __setattr__ so dot syntax works on keys."""
        self[key] = value


store = Store()


def timed_memoizer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fname = func.__qualname__
        logger.info("Started: %s" % fname)
        start_time = datetime.now()
        if fname in store.keys():
            ret = store[fname]
        else:
            logger.info("Return for {} not cached".format(fname))
            ret = await func(*args, **kwargs)
            store[fname] = ret
        logger.info("Finished: {} in: {} seconds".format(fname, datetime.now() - start_time))
        return ret

    return wrapper


@pytest.fixture(scope="module", autouse=True)
def copy_libraries_into_test_charm():
    """Ensure that the tester charm uses the current Prometheus library."""
    testers = ["loki-tester", "prometheus-tester"]
    for t in testers:
        if os.path.exists(f"tests/integration/{t}/lib"):
            shutil.rmtree(f"tests/integration/{t}/lib")
        shutil.copytree("lib", f"tests/integration/{t}/lib")


@pytest.fixture(scope="module")
@timed_memoizer
async def grafana_agent_charm(ops_test: OpsTest):
    """Loki charm used for integration testing."""
    count = 0
    # Intermittent issue where charmcraft fails to build the charm for an unknown reason.
    # Retry building the charm
    while True:
        try:
            charm = await ops_test.build_charm(".")
            return charm
        except RuntimeError:
            logger.warning("Failed to build grafana agent. Trying again!")
            count += 1

            if count == 3:
                raise


@pytest.fixture(scope="module")
@timed_memoizer
async def loki_tester_charm(ops_test):
    """A charm for integration test of the Loki charm."""
    charm_path = "tests/integration/loki-tester"
    clean_cmd = ["charmcraft", "clean", "-p", charm_path]
    await ops_test.run(*clean_cmd)
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
@timed_memoizer
async def prometheus_tester_charm(ops_test):
    """A charm for integration test of the Prometheus charm."""
    charm_path = "tests/integration/prometheus-tester"
    clean_cmd = ["charmcraft", "clean", "-p", charm_path]
    await ops_test.run(*clean_cmd)
    charm = await ops_test.build_charm(charm_path)
    return charm
