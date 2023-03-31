# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from charms.grafana_agent.v0.cos_agent import CosAgentClusterUnitData, COSAgentProvider
from ops.charm import CharmBase
from ops.framework import Framework
from scenario import PeerRelation, Relation, State, SubordinateRelation

from machine_charm import GrafanaAgentMachineCharm


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


def test_cos_agent_e2e(vroot):
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

    cos_agent = Relation("cos-agent")

    state_out = State(
        relations=[
            cos_agent,
        ]
    ).trigger(
        cos_agent.changed_event(remote_unit=1),
        charm_type=MyPrincipal,
        meta=MyPrincipal.META,
        charm_root=vroot,
    )

    # step 2: gagent is notified that the principal has touched its relation data
    peer = PeerRelation("cluster")
    cos_agent1 = SubordinateRelation(
        "cos-agent",
        primary_app_name="mock-principal",
        remote_unit_data=state_out.relations[0].local_unit_data,
    )
    state_out1 = State(relations=[cos_agent1, peer]).trigger(
        cos_agent1.changed_event(remote_unit=0),
        charm_type=GrafanaAgentMachineCharm,
        charm_root=vroot,
    )

    peer_out = state_out1.relations[1]
    peer_out_data = json.loads(peer_out.local_unit_data[CosAgentClusterUnitData.KEY])
    assert peer_out_data["principal_unit_name"] == "mock-principal/0"

    # step 3: gagent leader is notified that the principal has touched its relation data
    prometheus = Relation("send-remote-write", remote_app_name="prometheus-k8s")
    cos_agent2 = SubordinateRelation(
        "cos-agent",
        primary_app_name="mock-principal",
        remote_unit_data=state_out.relations[0].local_unit_data,
    )
    state_out2 = State(leader=True, relations=[cos_agent2, peer_out, prometheus]).trigger(
        peer_out.changed_event(remote_unit=0),
        charm_type=GrafanaAgentMachineCharm,
        charm_root=vroot,
    )

    prom_relation_out = state_out2.relations[2]

    # the prometheus lib has put some data in local app data towards cos-lite.
    assert prom_relation_out.local_app_data["alert_rules"]
