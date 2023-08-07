# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from charms.grafana_agent.v0.cos_agent import (
    CosAgentPeersUnitData,
    COSAgentProvider,
    COSAgentRequirer,
)
from ops.charm import CharmBase
from ops.framework import Framework
from scenario import Context, PeerRelation, State, SubordinateRelation


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
    with patch("subprocess.run", MagicMock()), patch(
        "grafana_agent.CONFIG_PATH", placeholder_cfg_path
    ):
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


@pytest.fixture(autouse=True)
def snap_is_installed():
    with patch(
        "machine_charm.GrafanaAgentMachineCharm._is_installed", new_callable=PropertyMock
    ) as mock_foo:
        mock_foo.return_value = True
        yield


@pytest.fixture
def provider_charm():
    class MyPrincipal(CharmBase):
        META = {
            "name": "mock-principal",
            "provides": {
                "cos-agent": {"interface": "cos_agent", "scope": "container"},
            },
        }
        _log_slots = ["charmed-kafka:logs"]

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.gagent = COSAgentProvider(
                self,
                metrics_endpoints=[
                    {"path": "/metrics", "port": "8080"},
                ],
                metrics_rules_dir="./src/alert_rules/prometheus",
                logs_rules_dir="./src/alert_rules/loki",
                log_slots=self._log_slots,
                refresh_events=[self.on.cos_agent_relation_changed],
            )

    return MyPrincipal


@pytest.fixture
def requirer_charm():
    class MySubordinate(CharmBase):
        META = {
            "name": "mock-subordinate",
            "requires": {
                "cos-agent": {"interface": "cos_agent", "scope": "container"},
            },
            "peers": {"peers": {"interface": "grafana_agent_replica"}},
        }

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.gagent = COSAgentRequirer(
                self,
                refresh_events=[self.on.cos_agent_relation_changed],
            )

    return MySubordinate


@pytest.fixture
def provider_ctx(provider_charm, vroot):
    return Context(charm_type=provider_charm, meta=provider_charm.META, charm_root=vroot)


@pytest.fixture
def requirer_ctx(requirer_charm, vroot):
    return Context(charm_type=requirer_charm, meta=requirer_charm.META, charm_root=vroot)


def test_cos_agent_changed_no_remote_data(provider_ctx):
    cos_agent = SubordinateRelation("cos-agent")
    state_out = provider_ctx.run(
        cos_agent.changed_event(remote_unit_id=1), State(relations=[cos_agent])
    )

    config = json.loads(state_out.relations[0].local_unit_data[CosAgentPeersUnitData.KEY])
    assert config["metrics_alert_rules"] == {}
    assert config["log_alert_rules"] == {}
    assert len(config["dashboards"]) == 1
    assert len(config["metrics_scrape_jobs"]) == 1
    assert config["log_slots"] == ["charmed-kafka:logs"]


def test_subordinate_update(requirer_ctx):
    # step 2: gagent is notified that the principal has touched its relation data
    peer = PeerRelation("peers")
    config = {
        "metrics_alert_rules": {},
        "log_alert_rules": {},
        "dashboards": [
            "/Td6WFoAAATm1rRGAgAhARYAAAB0L+WjAQAmCnsKICAidGl0bGUiOiAi"
            "Zm9vIiwKICAiYmFyIiA6ICJiYXoiCn0KAACkcc0YFt15xAABPyd8KlLdH7bzfQEAAAAABFla"
        ],
        "metrics_scrape_jobs": [
            {"job_name": "mock-principal_0", "path": "/metrics", "port": "8080"}
        ],
        "log_slots": ["charmed-kafka:logs"],
    }

    cos_agent1 = SubordinateRelation(
        "cos-agent",
        remote_app_name="mock-principal",
        remote_unit_data={"config": json.dumps(config)},
    )
    state_out1 = requirer_ctx.run(
        cos_agent1.changed_event(remote_unit_id=0), State(relations=[cos_agent1, peer])
    )
    peer_out = state_out1.get_relations("peers")[0]
    peer_out_data = json.loads(
        peer_out.local_unit_data[f"{CosAgentPeersUnitData.KEY}-mock-principal/0"]
    )
    assert peer_out_data["principal_unit_name"] == "mock-principal/0"
    assert peer_out_data["principal_relation_id"] == str(cos_agent1.relation_id)
    assert peer_out_data["principal_relation_name"] == cos_agent1.endpoint

    # passthrough as-is
    assert peer_out_data["metrics_alert_rules"] == config["metrics_alert_rules"]
    assert peer_out_data["log_alert_rules"] == config["log_alert_rules"]
    assert peer_out_data["dashboards"] == config["dashboards"]


def test_cos_agent_wrong_rel_data(vroot, snap_is_installed, provider_ctx):
    # Step 1: principal charm is deployed and ends in "unknown" state
    provider_ctx.charm_spec.charm_type._log_slots = (
        "charmed:frogs"  # Set wrong type, must be a list
    )
    cos_agent_rel = SubordinateRelation("cos-agent")
    state = State(relations=[cos_agent_rel])
    state_out = provider_ctx.run(cos_agent_rel.changed_event(remote_unit_id=1), state=state)
    assert state_out.unit_status.name == "unknown"

    found = False
    for log in provider_ctx.juju_log:
        if "ERROR" in log[0] and "Invalid relation data provided:" in log[1]:
            found = True
            break

    assert found is True
