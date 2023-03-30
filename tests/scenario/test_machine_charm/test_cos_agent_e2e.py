# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import tempfile
from pathlib import Path

from charms.grafana_agent.v0.cos_agent import (
    CosAgentClusterUnitData,
    COSAgentProvider,
    CosAgentProviderUnitData,
    COSAgentRequirer,
    GrafanaDashboard,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from ops.charm import CharmBase
from ops.framework import Framework
from scenario import PeerRelation, Relation, State, SubordinateRelation


class MyRequirerCharm(CharmBase):
    META = {
        "name": "test",
        "requires": {
            "cos-agent": {"interface": "cos_agent"},
            "send-remote-write": {"interface": "prometheus_remote_write"},
        },
        "peers": {"cluster": {"interface": "grafana_agent_replica"}},
    }

    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.cosagent = COSAgentRequirer(self)
        self.prom = PrometheusRemoteWriteConsumer(self)
        framework.observe(self.cosagent.on.data_changed, self._on_cosagent_data_changed)

    def _on_cosagent_data_changed(self, _):
        pass


def test_cos_agent_e2e():
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

    with tempfile.TemporaryDirectory() as vroot:
        vroot = Path(vroot)
        promroot = vroot / "src/alert_rules/prometheus"
        lokiroot = vroot / "src/alert_rules/loki"
        promroot.mkdir(parents=True)
        lokiroot.mkdir(parents=True)

        (promroot / "prom.rule").write_text(
            """alert: HostCpuHighIowait
expr: avg by (instance) (rate(node_cpu_seconds_total{mode="iowait"}[5m])) * 100 > 10
for: 0m
labels:
  severity: warning
annotations:
  summary: Host CPU high iowait (instance {{ $labels.instance }})
  description: "CPU iowait > 10%. A high iowait means that you are disk or network bound.\n  VALUE = {{ $value }}\n  LABELS = {{ $labels }}"
"""
        )
        (lokiroot / "loki.rule").write_text(
            """groups:
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
        )

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
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
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
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
    )

    prom_relation_out = state_out2.relations[2]
    # todo: ensure that the prometheus relation out should have some app data.
