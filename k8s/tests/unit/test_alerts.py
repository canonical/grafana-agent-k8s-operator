# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import yaml
from helpers import FakeProcessVersionCheck
from ops.model import Container
from ops.testing import Harness

from charm import (  # isort: skip <- needed because charm.py does not always exist
    GrafanaAgentK8sCharm,
)

PROMETHEUS_ALERT_RULES = {
    "groups": [
        {
            "name": "lma_f2c1b2a6_provider-tester_alerts",
            "rules": [
                {
                    "alert": "CPUOverUse",
                    "expr": 'process_cpu_seconds_total{juju_application="provider-tester",'
                    'juju_model="lma",'
                    'juju_model_uuid="81cafdbe-ccaa-4048-bd91-d3e5ece673ad"} > 0.12',
                    "for": "0m",
                    "labels": {
                        "severity": "Low",
                        "juju_model": "lma",
                        "juju_model_uuid": "81cafdbe-ccaa-4048-bd91-d3e5ece673ad",
                        "juju_application": "provider-tester",
                    },
                    "annotations": {
                        "summary": "Instance {{ $labels.instance }} CPU over use",
                        "description": "{{ $labels.instance }} of job "
                        "{{ $labels.job }} has used too much CPU.",
                    },
                },
                {
                    "alert": "PrometheusTargetMissing",
                    "expr": 'up{juju_application="provider-tester",juju_model="lma",'
                    'juju_model_uuid="81cafdbe-ccaa-4048-bd91-d3e5ece673ad"} == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "lma",
                        "juju_model_uuid": "81cafdbe-ccaa-4048-bd91-d3e5ece673ad",
                        "juju_application": "provider-tester",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "An exporter might be crashed.\n"
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
            ],
        }
    ]
}

LOKI_ALERT_RULES = {
    "groups": [
        {
            "name": "lma_81cafdbe-ccaa-4048-bd91-d3e5ece673ad_provider-tester_alerts",
            "rules": [
                {
                    "alert": "TooManyLogMessages",
                    "expr": 'count_over_time({job=".+",'
                    'juju_application="provider-tester",'
                    'juju_model="lma",'
                    'juju_model_uuid="81cafdbe-ccaa-4048-bd91-d3e5ece673ad"}[1m]) > 10',
                    "for": "0m",
                    "labels": {
                        "severity": "Low",
                        "juju_model": "lma",
                        "juju_model_uuid": "81cafdbe-ccaa-4048-bd91-d3e5ece673ad",
                        "juju_application": "provider-tester",
                    },
                    "annotations": {
                        "summary": "Instance {{ $labels.instance }} CPU over use",
                        "description": "{{ $labels.instance }} of job "
                        "{{ $labels.job }} has used too much CPU.",
                    },
                }
            ],
        }
    ]
}


@patch.object(Container, "restart", new=lambda x, y: True)
@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestAlertIngestion(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("grafana_agent.GrafanaAgentCharm.charm_dir", pathlib.Path("/"))
    @patch("grafana_agent.METRICS_RULES_SRC_PATH", tempfile.mkdtemp())
    @patch("grafana_agent.METRICS_RULES_DEST_PATH", tempfile.mkdtemp())
    @patch("grafana_agent.LOKI_RULES_SRC_PATH", tempfile.mkdtemp())
    @patch("grafana_agent.LOKI_RULES_DEST_PATH", tempfile.mkdtemp())
    @patch("grafana_agent.DASHBOARDS_SRC_PATH", tempfile.mkdtemp())
    @patch("grafana_agent.DASHBOARDS_DEST_PATH", tempfile.mkdtemp())
    @patch(
        "charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True
    )
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def setUp(self):
        self.harness = Harness(GrafanaAgentK8sCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_model_info(name="lma", uuid="1234567890")
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.metrics_path = self.harness.charm.metrics_rules_paths
        self.loki_path = self.harness.charm.loki_rules_paths
        self.harness.container_pebble_ready("agent")


class TestPrometheusRules(TestAlertIngestion):
    def test_consumes_prometheus_rules(self):
        rel_id = self.harness.add_relation("metrics-endpoint", "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(
            rel_id, "provider", {"alert_rules": json.dumps(PROMETHEUS_ALERT_RULES)}
        )

        rule_files = [f for f in pathlib.Path(self.metrics_path.dest).iterdir() if f.is_file()]

        rules = yaml.safe_load(rule_files[0].read_text())
        for group in rules["groups"]:
            if group["name"].endswith("provider-tester_alerts"):
                expr = group["rules"][0]["expr"]
                self.assertIn("juju_model", expr)
                self.assertIn("juju_model_uuid", expr)
                self.assertIn("juju_application", expr)
                self.assertNotIn("juju_unit", expr)
                self.assertEqual(
                    set(group["rules"][0]["labels"]),
                    {
                        "juju_application",
                        "juju_model",
                        "juju_model_uuid",
                        "severity",
                    },
                )
                break
        else:
            assert False  # Could not find the correct alert rule to check

    def test_forwards_prometheus_rules(self):
        rel_id = self.harness.add_relation("metrics-endpoint", "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        prom_id = self.harness.add_relation("send-remote-write", "prom")
        self.harness.add_relation_unit(prom_id, "prom/0")

        self.harness.update_relation_data(
            rel_id, "provider", {"alert_rules": json.dumps(PROMETHEUS_ALERT_RULES)}
        )

        data = self.harness.get_relation_data(prom_id, self.harness.model.app.name)
        rules = json.loads(data["alert_rules"])

        for group in rules["groups"]:
            if group["name"].endswith("provider-tester_alerts"):
                expr = group["rules"][0]["expr"]
                self.assertIn("juju_model", expr)
                self.assertIn("juju_model_uuid", expr)
                self.assertIn("juju_application", expr)
                self.assertNotIn("juju_unit", expr)
                self.assertEqual(
                    set(group["rules"][0]["labels"]),
                    {
                        "juju_application",
                        "juju_model",
                        "juju_charm",
                        "juju_model_uuid",
                        "severity",
                    },
                )
                break
        else:
            assert False  # Could not find the correct alert rule to check


class TestLokiRules(TestAlertIngestion):
    def test_consumes_loki_rules(self):
        rel_id = self.harness.add_relation("logging-provider", "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer", {"alert_rules": json.dumps(LOKI_ALERT_RULES)}
        )

        rule_files = [f for f in pathlib.Path(self.loki_path.dest).iterdir() if f.is_file()]

        rules = yaml.safe_load(rule_files[0].read_text())
        for group in rules["groups"]:
            if group["name"].endswith("provider-tester_alerts"):
                expr = group["rules"][0]["expr"]
                self.assertIn("juju_model", expr)
                self.assertIn("juju_model_uuid", expr)
                self.assertIn("juju_application", expr)
                self.assertNotIn("juju_unit", expr)
                self.assertEqual(
                    set(group["rules"][0]["labels"]),
                    {
                        "juju_application",
                        "juju_model",
                        "juju_model_uuid",
                        "severity",
                    },
                )
                break
        else:
            assert False  # Could not find the correct alert rule to check

    def test_forwards_loki_rules(self):
        rel_id = self.harness.add_relation("logging-provider", "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")

        loki_id = self.harness.add_relation("logging-consumer", "loki")
        self.harness.add_relation_unit(loki_id, "loki/0")

        self.harness.update_relation_data(
            rel_id, "consumer", {"alert_rules": json.dumps(LOKI_ALERT_RULES)}
        )

        data = self.harness.get_relation_data(loki_id, self.harness.model.app.name)
        rules = json.loads(data["alert_rules"])

        for group in rules["groups"]:
            if group["name"].endswith("provider-tester_alerts_alerts"):
                expr = group["rules"][0]["expr"]
                self.assertIn("juju_model", expr)
                self.assertIn("juju_model_uuid", expr)
                self.assertIn("juju_application", expr)
                self.assertNotIn("juju_unit", expr)
                self.assertEqual(
                    set(group["rules"][0]["labels"]),
                    {
                        "juju_application",
                        "juju_model",
                        "juju_model_uuid",
                        "juju_charm",
                        "severity",
                    },
                )
                break
        else:
            assert False  # Could not find the correct alert rule to check
