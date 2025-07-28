# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import grp
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import List

import yaml
from asyncstdlib import functools
from grafana import Grafana
from lightkube import Client
from lightkube.resources.core_v1 import Pod
from prometheus import Prometheus
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def get_unit_address(ops_test, app_name: str, unit_num: int) -> str:
    status = await ops_test.model.get_status()  # noqa: F821
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def is_loki_up(ops_test, app_name, num_units=1) -> bool:
    # Sometimes get_unit_address returns a None, no clue why, so looping until it's not
    addresses = [""] * num_units
    while not all(addresses):
        addresses = [await get_unit_address(ops_test, app_name, i) for i in range(num_units)]

    def get(url) -> bool:
        response = urllib.request.urlopen(url, data=None, timeout=2.0)
        return response.code == 200 and "version" in json.loads(response.read())

    return all(get(f"http://{address}:3100/loki/api/v1/status/buildinfo") for address in addresses)


async def loki_rules(ops_test, app_name) -> dict:
    address = await get_unit_address(ops_test, app_name, 0)
    url = f"http://{address}:3100"

    try:
        response = urllib.request.urlopen(f"{url}/loki/api/v1/rules", data=None, timeout=2.0)
        if response.code == 200:
            return yaml.safe_load(response.read())
        return {}
    except urllib.error.HTTPError:
        return {}


async def loki_alerts(ops_test: str, app_name: str, unit_num: int = 0, retries: int = 3) -> dict:
    r"""Get a list of alerts from a Prometheus-compatible endpoint.

    Results look like:
        {
          "data": {
              "groups": [
                  {
                      "rules": [
                          {
                              "alerts": [
                                  {
                                      "activeAt": "2018-07-04T20:27:12.60602144+02:00",
                                      "annotations": {
                                          "summary": "High request latency"
                                      },
                                      "labels": {
                                          "alertname": "HighRequestLatency",
                                          "severity": "page"
                                      },
                                      "state": "firing",
                                      "value": "1e+00"
                                  }
                              ],
                              "annotations": {
                                  "summary": "High request latency"
                              },
                              "duration": 600,
                              "health": "ok",
                              "labels": {
                                  "severity": "page"
                              },
                              "name": "HighRequestLatency",
                              "query": "job:request_latency_seconds:mean5m{job=\"myjob\"} > 0.5",
                              "type": "alerting"
                          },
                          {
                              "health": "ok",
                              "name": "job:http_inprogress_requests:sum",
                              "query": "sum by (job) (http_inprogress_requests)",
                              "type": "recording"
                          }
                      ],
                      "file": "/rules.yaml",
                      "interval": 60,
                      "limit": 0,
                      "name": "example"
                  }
              ]
          },
          "status": "success"
        }
    """
    address = await get_unit_address(ops_test, app_name, unit_num)
    url = f"http://{address}:3100/prometheus/api/v1/alerts"

    # Retry since the endpoint may not _immediately_ return valid data
    while not (
        alerts := json.loads(urllib.request.urlopen(url, data=None, timeout=2).read())["data"][
            "alerts"
        ]
    ):
        retries -= 1
        if retries > 0:
            await asyncio.sleep(2)
        else:
            break

    return alerts


async def unit_address(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Find unit address for any application.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
        unit_num: integer number of a juju unit

    Returns:
        unit address as a string
    """
    assert ops_test.model
    status = await ops_test.model.get_status()
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def prometheus_rules(ops_test: OpsTest, app_name: str, unit_num: int) -> list:
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


def oci_image(charmcraft_file: str, image_name: str) -> str:
    """Find upstream source for a container image.

    Args:
        charmcraft_file: string path of charmcraft YAML file relative
            to top level charm directory
        image_name: OCI container image string name as defined in
            metadata.yaml file
    Returns:
        upstream image source
    Raises:
        FileNotFoundError: if charmcraft_file path is invalid
        ValueError: if upstream source for image name can not be found
    """
    metadata = yaml.safe_load(Path(charmcraft_file).read_text())

    resources = metadata.get("resources", {})
    if not resources:
        raise ValueError("No resources found")

    image = resources.get(image_name, {})
    if not image:
        raise ValueError("{} image not found".format(image_name))

    upstream_source = image.get("upstream-source", "")
    if not upstream_source:
        raise ValueError("Upstream source not found")

    return upstream_source


def initial_workload_is_ready(ops_test, app_names) -> bool:
    """Checks that the initial workload (ie. x/0) is ready.

    Args:
        ops_test: pytest-operator plugin
        app_names: array of application names to check for

    Returns:
        whether the workloads are active or not
    """
    return all(
        ops_test.model.applications[name].units[0].workload_status == "active"
        for name in app_names
    )


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
    assert ops_test.model
    application = ops_test.model.applications[app_name]
    assert application
    action = await application.units[unit_num].run_action("get-admin-password")
    action = await action.wait()
    return action.results["admin-password"]


async def get_grafana_dashboards(ops_test: OpsTest, app_name: str, unit_num: int) -> list:
    """Find a dashboard by searching.

    This method finds a dashboard through the search API. It isn't
    possible to return the JSON for all dashboards, so we need to
    look through a query and fetch them.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Grafana application
        unit_num: integer number of a Grafana juju unit

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


def uk8s_group() -> str:
    try:
        # Classically confined microk8s
        uk8s_group = grp.getgrnam("microk8s").gr_name
    except KeyError:
        # Strictly confined microk8s
        uk8s_group = "snap_microk8s"
    return uk8s_group


def get_podspec(ops_test: OpsTest, app_name: str, container_name: str):
    assert ops_test.model_name
    client = Client()
    pod = client.get(Pod, name=f"{app_name}-0", namespace=ops_test.model_name)
    assert pod.spec
    podspec = next(iter(filter(lambda ctr: ctr.name == container_name, pod.spec.containers)))
    return podspec
