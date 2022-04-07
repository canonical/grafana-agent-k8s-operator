# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, patch

import responses
import yaml
from charms.loki_k8s.v0.loki_push_api import (
    LokiPushApiEndpointDeparted,
    LokiPushApiEndpointJoined,
)
from deepdiff import DeepDiff  # type: ignore
from ops.framework import Handle
from ops.model import ActiveStatus, BlockedStatus, Container
from ops.testing import Harness

from charm import GrafanaAgentOperatorCharm, GrafanaAgentReloadError

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


class TestCharm(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def setUp(self):
        self.harness = Harness(GrafanaAgentOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_model_info(name="lma", uuid="1234567890")
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    @responses.activate
    @patch.object(Container, "restart")
    def test_remote_write_configuration(self, mock_restart: MagicMock):
        mock_restart.restart.return_value = True
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
            "prometheus": {
                "configs": [
                    {
                        "name": "agent_scraper",
                        "remote_write": [
                            {"url": "http://1.1.1.2:9090/api/v1/write"},
                            {"url": "http://1.1.1.1:9090/api/v1/write"},
                        ],
                        "scrape_configs": [],
                    }
                ]
            },
            "server": {"log_level": "info"},
            "loki": {},
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
            config["prometheus"]["configs"][0]["remote_write"],
            [{"url": "http://1.1.1.1:9090/api/v1/write"}],
        )

        # Test scale to zero
        self.harness.remove_relation_unit(rel_id, "prometheus/0")

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        self.assertEqual(config["integrations"]["prometheus_remote_write"], [])
        self.assertEqual(config["prometheus"]["configs"][0]["remote_write"], [])

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
        expected = "-config.file=/etc/agent/agent.yaml -prometheus.wal-directory=/tmp/agent/data"
        self.assertEqual(self.harness.charm._cli_args(), expected)

    @responses.activate
    def test__on_loki_push_api_endpoint_joined(self):
        """Test Loki config is in config file when LokiPushApiEndpointJoined is fired."""
        agent_container = self.harness.charm.unit.get_container("agent")

        self.harness.charm._loki_consumer = Mock()
        self.harness.charm._loki_consumer.loki_endpoints = [
            {"url": "http://loki:3100:/loki/api/v1/push"}
        ]

        self.harness.add_relation("logging-provider", "otherapp")
        handle = Handle(None, "kind", "Key")
        event = LokiPushApiEndpointJoined(handle)
        self.harness.charm._on_loki_push_api_endpoint_joined(event)

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        expected = {
            "configs": [
                {
                    "name": "promtail",
                    "clients": [{"url": "http://loki:3100:/loki/api/v1/push"}],
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
        self.assertDictEqual(config["loki"], expected)

    @responses.activate
    def test__on_loki_push_api_endpoint_departed(self):
        """Test Loki config is not in config file when LokiPushApiEndpointDeparted is fired."""
        agent_container = self.harness.charm.unit.get_container("agent")

        self.harness.charm._loki_consumer = Mock()
        self.harness.charm._loki_consumer.loki_push_api = "http://loki:3100:/loki/api/v1/push"

        handle = Handle(None, "kind", "Key")
        event = LokiPushApiEndpointDeparted(handle)
        self.harness.charm._on_loki_push_api_endpoint_departed(event)

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        self.assertTrue(config["loki"] == {})

    def test__agent_reload_fails(self):
        self.harness.charm._container.replan = Mock(side_effect=GrafanaAgentReloadError)
        self.harness.charm._update_config()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("could not reload configuration")
        )
