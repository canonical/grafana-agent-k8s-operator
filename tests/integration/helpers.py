#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import List

from asyncstdlib import functools
from grafana import Grafana
from prometheus import Prometheus
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)


async def unit_address(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Find unit address for any application.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
        unit_num: integer number of a juju unit

    Returns:
        unit address as a string
    """
    status = await ops_test.model.get_status()
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


@functools.cache
async def unit_password(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Get the admin password for a unit. Memoize it to reduce turnaround time.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
        unit_num: integer number of a juju unit

    Returns:
        admin password as a string
    """
    action = (
        await ops_test.model.applications[app_name]
        .units[unit_num]
        .run_action("get-admin-password")
    )
    action = await action.wait()
    return action.results["admin-password"]


async def get_grafana_dashboards(ops_test: OpsTest, app_name: str, unit_num: int) -> list:
    """Find a dashboard by searching.

    This method finds a dashboard through the search API. It isn't
    possible to return the JSON for all dashboards, so we need to
    look through a query and fetch them.

    Args:
        app_name: string name of Grafana application

    Returns:
        a list of dashboards
    """
    host = await unit_address(ops_test, app_name, unit_num)
    pw = await unit_password(ops_test, app_name, unit_num)
    grafana = Grafana(host=host, pw=pw)
    dashboards = await grafana.dashboards_all()
    return dashboards


async def get_prometheus_rules(ops_test: OpsTest, app_name: str, unit_num: int) -> list:
    """Fetch all Prometheus rules.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        a list of rule groups.
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    rules = await prometheus.rules()
    return rules


async def get_prometheus_active_targets(
    ops_test: OpsTest, app_name: str, unit_num: int = 0
) -> List[dict]:
    """Fetch Prometheus active scrape targets.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        Prometheus YAML configuration in string format.
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    targets = await prometheus.active_targets()
    return targets
