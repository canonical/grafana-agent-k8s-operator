# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import tempfile
import unittest
from typing import Any, Dict
from unittest.mock import patch

import ops.testing
import responses
import yaml
from deepdiff import DeepDiff  # type: ignore
from ops.model import ActiveStatus, BlockedStatus, Container
from ops.testing import Harness

from charm import GrafanaAgentOperatorCharm

ops.testing.SIMULATE_CAN_CONNECT = True

SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "abcdef",
    "application": "consumer",
}

SCRAPE_JOBS = [
    {
        "job_name": "my-job",
        "static_configs": [
            {"targets": ["*:8000"], "labels": {"some-other-key": "some-other-value"}}
        ],
    },
]

REWRITE_CONFIGS = [
    {
        "target_label": "job",
        "regex": "(.*)",
        "replacement": "juju_lma_1234567890_grafana-agent-k8s_self-monitoring",
    },
    {
        "target_label": "instance",
        "regex": "(.*)",
        "replacement": "lma_1234567890_grafana-agent-k8s_grafana-agent-k8s/0",
    },
    {
        "source_labels": ["__address__"],
        "target_label": "juju_charm",
        "replacement": "grafana-agent-k8s",
    },
    {
        "source_labels": ["__address__"],
        "target_label": "juju_model",
        "replacement": "lma",
    },
    {
        "source_labels": ["__address__"],
        "target_label": "juju_model_uuid",
        "replacement": "1234567890",
    },
    {
        "source_labels": ["__address__"],
        "target_label": "juju_application",
        "replacement": "grafana-agent-k8s",
    },
    {
        "source_labels": ["__address__"],
        "target_label": "juju_unit",
        "replacement": "grafana-agent-k8s/0",
    },
]


@patch.object(Container, "restart", new=lambda x, y: True)
@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestScrapeConfiguration(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.METRICS_RULES_SRC_PATH", tempfile.mkdtemp())
    @patch("charm.METRICS_RULES_DEST_PATH", tempfile.mkdtemp())
    @patch("charm.LOKI_RULES_SRC_PATH", tempfile.mkdtemp())
    @patch("charm.LOKI_RULES_DEST_PATH", tempfile.mkdtemp())
    @patch(
        "charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True
    )
    def setUp(self):
        self.harness = Harness(GrafanaAgentOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_model_info(name="lma", uuid="1234567890")
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("agent")

    @responses.activate
    def test_remote_write_configuration(self):
        responses.add(
            responses.POST,
            "http://localhost/-/reload",
            status=200,
        )

        agent_container = self.harness.charm.unit.get_container("agent")

        rel_id = self.harness.add_relation("send-remote-write", "prometheus")

        self.harness.add_relation_unit(rel_id, "prometheus/0")
        self.harness.update_relation_data(
            rel_id,
            "prometheus/0",
            {"remote_write": json.dumps({"url": "http://1.1.1.1:9090/api/v1/write"})},
        )

        self.harness.add_relation_unit(rel_id, "prometheus/1")
        self.harness.update_relation_data(
            rel_id,
            "prometheus/1",
            {"remote_write": json.dumps({"url": "http://1.1.1.2:9090/api/v1/write"})},
        )

        expected_config: Dict[str, Any] = {
            "integrations": {
                "agent": {
                    "enabled": True,
                    "relabel_configs": REWRITE_CONFIGS,
                },
                "prometheus_remote_write": [
                    {"url": "http://1.1.1.2:9090/api/v1/write"},
                    {"url": "http://1.1.1.1:9090/api/v1/write"},
                ],
            },
            "metrics": {
                "wal_directory": "/tmp/agent/data",
                "configs": [
                    {
                        "name": "agent_scraper",
                        "remote_write": [
                            {"url": "http://1.1.1.2:9090/api/v1/write"},
                            {"url": "http://1.1.1.1:9090/api/v1/write"},
                        ],
                        "scrape_configs": [],
                    }
                ],
            },
            "server": {"log_level": "info"},
            "logs": {},
        }

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        self.assertEqual(DeepDiff(expected_config, config, ignore_order=True), {})
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

        # Test scale down
        self.harness.remove_relation_unit(rel_id, "prometheus/1")

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        self.assertEqual(
            config["integrations"]["prometheus_remote_write"],
            [{"url": "http://1.1.1.1:9090/api/v1/write"}],
        )
        self.assertEqual(
            config["metrics"]["configs"][0]["remote_write"],
            [{"url": "http://1.1.1.1:9090/api/v1/write"}],
        )

        # Test scale to zero
        self.harness.remove_relation_unit(rel_id, "prometheus/0")

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        self.assertEqual(config["integrations"]["prometheus_remote_write"], [])
        self.assertEqual(config["metrics"]["configs"][0]["remote_write"], [])

    @responses.activate
    def test_scrape_without_remote_write_configuration(self):
        agent_container = self.harness.charm.unit.get_container("agent")

        responses.add(
            responses.POST,
            "http://localhost/-/reload",
            status=200,
        )

        rel_id = self.harness.add_relation("metrics-endpoint", "foo")

        self.harness.add_relation_unit(rel_id, "foo/0")
        self.harness.update_relation_data(
            rel_id,
            "foo/0",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "scrape_jobs": json.dumps(SCRAPE_JOBS),
            },
        )

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())
        self.assertDictEqual(
            config["integrations"],
            {
                "agent": {
                    "enabled": True,
                    "relabel_configs": REWRITE_CONFIGS,
                },
                "prometheus_remote_write": [],
            },
        )

        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("no related Prometheus remote-write")
        )

    def test__cli_args(self):
        expected = "-config.file=/etc/agent/agent.yaml"
        self.assertEqual(self.harness.charm._cli_args(), expected)

    # Leaving this test here as we need to use it again when we figure out how to
    # fix _reload_config.

    # def test__agent_reload_fails(self):
    #     self.harness.charm._container.replan = Mock(side_effect=GrafanaAgentReloadError)
    #     self.harness.charm._update_config()
    #     self.assertEqual(
    #         self.harness.charm.unit.status, BlockedStatus("could not reload configuration")
    #     )

    def test_loki_config_with_and_without_loki_endpoints(self):
        rel_id = self.harness.add_relation("logging-consumer", "loki")

        for u in range(2):
            self.harness.add_relation_unit(rel_id, f"loki/{u}")
            endpoint = json.dumps({"url": f"http://loki{u}:3100:/loki/api/v1/push"})
            self.harness.update_relation_data(rel_id, f"loki/{u}", {"endpoint": endpoint})

        expected = {
            "logs": {
                "configs": [
                    {
                        "name": "promtail",
                        "clients": [
                            {"url": "http://loki0:3100:/loki/api/v1/push"},
                            {"url": "http://loki1:3100:/loki/api/v1/push"},
                        ],
                        "positions": {"filename": "/tmp/positions.yaml"},
                        "scrape_configs": [
                            {
                                "job_name": "loki",
                                "loki_push_api": {
                                    "server": {
                                        "http_listen_port": 3500,
                                        "grpc_listen_port": 3600,
                                    },
                                },
                            }
                        ],
                    }
                ]
            }
        }
        self.assertEqual(
            DeepDiff(expected, self.harness.charm._loki_config(), ignore_order=True), {}
        )

        self.harness.remove_relation(rel_id)
        self.assertEqual({"logs": {}}, self.harness.charm._loki_config())
