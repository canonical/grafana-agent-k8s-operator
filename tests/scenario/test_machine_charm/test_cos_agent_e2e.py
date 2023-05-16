# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from charms.grafana_agent.v0.cos_agent import CosAgentPeersUnitData, COSAgentProvider
from machine_charm import GrafanaAgentMachineCharm
from ops.charm import CharmBase
from ops.framework import Framework
from scenario import Context, PeerRelation, Relation, State, SubordinateRelation


@pytest.fixture
def placeholder_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"


PROM_RULE = """alert: HostCpuHighIowait
expr: avg by (instance) (rate(node_cpu_seconds_total{mode="iowait"}[5m])) * 100 > 10
for: 0m
labels:
  severity: warning
annotations:
  summary: Host CPU high iowait (instance {{ $labels.instance }})
  description: "CPU iowait > 10%. A high iowait means that you are disk or network bound.\n  VALUE = {{ $value }}\n  LABELS = {{ $labels }}"
"""
LOKI_RULE = """groups:
  - name: grafana-agent-high-log-volume
    rules:
      - alert: HighLogVolume
        expr: |
          count_over_time(({%%juju_topology%%})[30s]) > 100
        labels:
            severity: high
        annotations:
            summary: Log rate is too high!
"""
GRAFANA_DASH = """
{
  "title": "foo",
  "bar" : "baz"
}
"""


@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("subprocess.run", MagicMock()):
        with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
            yield


@pytest.fixture(autouse=True)
def vroot(placeholder_cfg_path):
    with tempfile.TemporaryDirectory() as vroot:
        vroot = Path(vroot)
        promroot = vroot / "src/prometheus_alert_rules"
        lokiroot = vroot / "src/loki_alert_rules"
        grafroot = vroot / "src/grafana_dashboards"

        promroot.mkdir(parents=True)
        lokiroot.mkdir(parents=True)
        grafroot.mkdir(parents=True)

        (promroot / "prom.rule").write_text(PROM_RULE)
        (lokiroot / "loki.rule").write_text(LOKI_RULE)
        (grafroot / "grafana_dashboard.json").write_text(GRAFANA_DASH)

        old_cwd = os.getcwd()
        os.chdir(str(vroot))
        yield vroot
        os.chdir(old_cwd)


@pytest.fixture
def snap_is_installed(autouse=True):
    with patch(
        "machine_charm.GrafanaAgentMachineCharm._is_installed", new_callable=PropertyMock
    ) as mock_foo:
        mock_foo.return_value = True
        yield


def test_cos_agent_e2e(vroot, snap_is_installed):
    class MyPrincipal(CharmBase):
        META = {"name": "mock-principal", "provides": {"cos-agent": {"interface": "cos_agent"}}}

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.gagent = COSAgentProvider(
                self,
                metrics_endpoints=[
                    {"path": "/metrics", "port": "8080"},
                ],
                metrics_rules_dir="./src/alert_rules/prometheus",
                logs_rules_dir="./src/alert_rules/loki",
                log_slots=["charmed-kafka:logs"],
                refresh_events=[self.on.cos_agent_relation_changed],
            )

    # Step 1: gagent is deployed and ends in "unknown" state
    # since it is not related to the principal charm.
    cos_agent = Relation("cos-agent")
    ctx = Context(
        charm_type=MyPrincipal,
        meta=MyPrincipal.META,
        charm_root=vroot,
    )

    state = State(relations=[cos_agent])
    state_out = ctx.run(cos_agent.changed_event(remote_unit_id=1), state=state)
    assert state_out.status.unit.name == "unknown"

    # Step 2: gagent is related to principal charm and ends in "blocked" status
    # since there are missing relations:
    #  - send-remote-write
    #  - logging-consumer
    #  - grafana-dashboards-provider
    peer = PeerRelation("peers")
    cos_agent1 = SubordinateRelation(
        "cos-agent",
        primary_app_name="mock-principal",
        remote_unit_data=state_out.relations[0].local_unit_data,
    )

    ctx1 = Context(
        charm_type=GrafanaAgentMachineCharm,
        charm_root=vroot,
    )
    state1 = State(relations=[cos_agent1, peer])
    state_out1 = ctx1.run(cos_agent1.changed_event(remote_unit_id=0), state=state1)
    assert state_out1.status.unit.name == "blocked"

    peer_out = state_out1.relations[1]
    peer_out_data = json.loads(peer_out.local_unit_data[CosAgentPeersUnitData.KEY])
    assert peer_out_data["principal_unit_name"] == "mock-principal/0"

    # Step 3: gagent is related to Prometheus through "send-remote-write" relation and ends
    # in "blocked" status since there are missing relations:
    #  - logging-consumer
    #  - grafana-dashboards-provider
    prometheus = Relation("send-remote-write", remote_app_name="prometheus-k8s")
    cos_agent2 = SubordinateRelation(
        "cos-agent",
        primary_app_name="mock-principal",
        remote_unit_data=state_out.relations[0].local_unit_data,
    )
    ctx2 = Context(
        charm_type=GrafanaAgentMachineCharm,
        charm_root=vroot,
    )
    state2 = State(leader=True, relations=[cos_agent2, peer_out, prometheus])
    state_out2 = ctx2.run(peer_out.changed_event(remote_unit_id=0), state=state2)
    prom_relation_out = state_out2.relations[2]
    # the prometheus lib has put some data in local app data towards cos-lite.
    assert prom_relation_out.local_app_data["alert_rules"]

    # Step 4: gagent is related to Loki through "logging-consumer" relation and ends
    # in "blocked" status since there are missing relations:
    #  - grafana-dashboards-provider
    loki = Relation("logging-consumer", remote_app_name="lok-k8s")
    state3 = State(leader=True, relations=[cos_agent2, peer_out, prometheus, loki])
    state_out3 = ctx2.run(peer_out.changed_event(remote_unit_id=0), state=state3)
    assert state_out3.status.unit.name == "blocked"

    # Step 5: gagent is related to Grafana through "grafana-dashboards-provider" relation and ends
    # in "active" status
    grafana = Relation("grafana-dashboards-provider", remote_app_name="grafana-k8s")
    state4 = State(leader=True, relations=[cos_agent2, peer_out, prometheus, loki, grafana])
    state_out4 = ctx2.run(peer_out.changed_event(remote_unit_id=0), state=state4)
    assert state_out4.status.unit.name == "active"


def test_cos_agent_wrong_rel_data(vroot, snap_is_installed):
    class MyPrincipal(CharmBase):
        META = {"name": "mock-principal", "provides": {"cos-agent": {"interface": "cos_agent"}}}

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.gagent = COSAgentProvider(
                self,
                log_slots="charmed-kafka:logs",  # Set wrong type, must be a list
                refresh_events=[self.on.cos_agent_relation_changed],
            )

    # Step 1: gagent is deployed and ends in "unknown" state
    # since it is not related to the principal charm.
    cos_agent = Relation("cos-agent")
    ctx = Context(
        charm_type=MyPrincipal,
        meta=MyPrincipal.META,
        charm_root=vroot,
    )

    state = State(relations=[cos_agent])
    state_out = ctx.run(cos_agent.changed_event(remote_unit_id=1), state=state)
    assert state_out.status.unit.name == "unknown"

    # Step 2: gagent is related to principal charm and ends in "blocked" status
    # since there are missing relations:

    peer = PeerRelation("peers")
    cos_agent1 = SubordinateRelation(
        "cos-agent",
        primary_app_name="mock-principal",
        remote_unit_data=state_out.relations[0].local_unit_data,
    )

    ctx1 = Context(
        charm_type=GrafanaAgentMachineCharm,
        charm_root=vroot,
    )
    state1 = State(relations=[cos_agent1, peer])
    state_out1 = ctx1.run(cos_agent1.changed_event(remote_unit_id=0), state=state1)
    assert state_out1.status.unit.name == "blocked"
    assert "Validation errors" in state_out1.status.unit.message
