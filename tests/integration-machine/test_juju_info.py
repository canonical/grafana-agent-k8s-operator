# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import List

import pytest
from juju.errors import JujuError
from pytest_operator.plugin import OpsTest

agent = SimpleNamespace(name="agent")
principal = SimpleNamespace(charm="ubuntu", name="principal")

logger = logging.getLogger(__name__)

topology_labels = {
    "juju_application",
    # "juju_charm",  # juju_charm is present in the grafana agent's self scrape only
    "juju_model",
    "juju_model_uuid",
    "juju_unit",
}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, grafana_agent_charm):
    await asyncio.gather(
        # Principal
        ops_test.model.deploy(
            principal.charm, application_name=principal.name, num_units=2, series="jammy"
        ),
        # Subordinate
        ops_test.model.deploy(
            grafana_agent_charm, application_name=agent.name, num_units=0, series="jammy"
        ),
    )

    # grafana agent is in 'unknown' status until related, so wait only for the principal
    await ops_test.model.wait_for_idle(apps=[principal.name])


@pytest.mark.abort_on_fail
async def test_service(ops_test: OpsTest):
    # WHEN the charm is related to a principal over `juju-info`
    await ops_test.model.add_relation("agent:juju-info", principal.name)
    await ops_test.model.wait_for_idle(status="active")

    # THEN all units of the principal have the charm in 'enabled/active' state
    # $ juju ssh agent/0 snap services grafana-agent
    # Service                      Startup  Current  Notes
    # grafana-agent.grafana-agent  enabled  active   -
    machines: List[str] = await ops_test.model.get_machines()
    for machine_id in machines:
        try:
            await ops_test.model.machines[machine_id].ssh(
                "snap services grafana-agent | grep 'enabled.*active'"
            )
        except JujuError as e:
            pytest.fail(f"snap is not enabled/active in unit {machine_id}: {e.message}")


@pytest.mark.abort_on_fail
async def test_metrics(ops_test: OpsTest):
    # Wait the scrape interval to make sure all "state" keys turned from unknown to up (or down).
    await asyncio.sleep(60)

    machines: List[str] = await ops_test.model.get_machines()

    # AND juju topology labels are present for all targets and all targets are 'up'
    machine_targets = {
        machine_id: await ops_test.model.machines[machine_id].ssh(
            "curl localhost:12345/agent/api/v1/metrics/targets"
        )
        for machine_id in machines
    }
    machine_targets = {k: json.loads(v)["data"] for k, v in machine_targets.items()}
    for targets in machine_targets.values():
        for target in targets:
            target_labels = target["labels"].keys()
            assert topology_labels.issubset(target_labels)
            assert target["state"] == "up"

    # $ juju ssh agent/0 curl localhost:12345/agent/api/v1/metrics/targets
    # {
    #   "status": "success",
    #   "data": [
    #     {
    #       "instance": "243a344db344241f404868d04272fc76",
    #       "target_group": "integrations/agent",
    #       "endpoint": "http://127.0.0.1:12345/integrations/agent/metrics",
    #       "state": "up",
    #       "labels": {
    #         "agent_hostname": "juju-f48d37-1",
    #         "instance": "test-charm-hz7v_8df47ec8-0c18-..._principal_principal/1",
    #         "job": "juju_test-charm-hz7v_8df47ec8-0c18-..._agent_self-monitoring",
    #         "juju_application": "agent",
    #         "juju_charm": "grafana-agent",
    #         "juju_model": "test-charm-hz7v",
    #         "juju_model_uuid": "8df47ec8-0c18-465a-8b68-a07188f48d37",
    #         "juju_unit": "agent/0"
    #       },
    #       "discovered_labels": {
    #         "__address__": "127.0.0.1:12345",
    #         "__metrics_path__": "/integrations/agent/metrics",
    #         "__scheme__": "http",
    #         "__scrape_interval__": "1m",
    #         "__scrape_timeout__": "10s",
    #         "agent_hostname": "juju-f48d37-1",
    #         "job": "integrations/agent"
    #       },
    #       "last_scrape": "2023-03-09T22:31:16.5693783Z",
    #       "scrape_duration_ms": 2,
    #       "scrape_error": ""
    #     },
    #     ...


@pytest.mark.xfail  # agent return an empty reply (bug)
async def test_logs(ops_test: OpsTest):
    machines: List[str] = await ops_test.model.get_machines()

    # AND juju topology labels are present for all targets
    machine_targets = {
        machine_id: await ops_test.model.machines[machine_id].ssh(
            "curl localhost:12345/agent/api/v1/logs/targets"
        )
        for machine_id in machines
    }
    machine_targets = {k: json.loads(v)["data"] for k, v in machine_targets.items()}
    for targets in machine_targets.values():
        for target in targets:
            target_labels = target["labels"].keys()
            assert topology_labels.issubset(target_labels)
