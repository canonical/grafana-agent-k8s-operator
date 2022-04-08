# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, patch

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


SELF_MONITORING_SCRAPE = {
    "job_name": "agent_self_monitoring_lma_1234567890_grafana-agent-k8s-0",
    "metrics_path": "/metrics",
    "relabel_configs": [
        {
            "regex": "(.*)",
            "separator": "_",
            "source_labels": [
                "juju_model",
                "juju_model_uuid",
                "juju_application",
                "juju_unit",
            ],
            "target_label": "instance",
        }
    ],
    "scrape_interval": "5s",
    "static_configs": [
        {
            "labels": {
                "juju_charm": "grafana-agent-k8s",
                "juju_model": "lma",
                "juju_model_uuid": "1234567890",
                "juju_application": "grafana-agent-k8s",
                "juju_unit": "grafana-agent-k8s/0",
            },
            "targets": ["localhost"],
        }
    ],
}


SCRAPE_JOBS = [SELF_MONITORING_SCRAPE] + [
    {
        "job_name": "my-job",
        "static_configs": [
            {"targets": ["*:8000"], "labels": {"some-other-key": "some-other-value"}}
        ],
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

    @patch.object(Container, "restart")
    def test_remote_write_configuration(self, mock_restart: MagicMock):
        mock_restart.restart.return_value = True

        agent_container = self.harness.charm.unit.get_container("agent")

        rel_id = self.harness.add_relation("send-remote-write", "prometheus")

        self.harness.add_relation_unit(rel_id, "prometheus/0")
        self.harness.update_relation_data(
            rel_id,
            "prometheus/0",
            {"remote_write": json.dumps({"url": "http://1.1.1.1:9090/api/v1/write"})},
        )

        mock_restart.assert_called_with("agent")
        mock_restart.reset_mock()

        self.harness.add_relation_unit(rel_id, "prometheus/1")
        self.harness.update_relation_data(
            rel_id,
            "prometheus/1",
            {"remote_write": json.dumps({"url": "http://1.1.1.2:9090/api/v1/write"})},
        )

        mock_restart.assert_called_once_with("agent")
        mock_restart.reset_mock()

        expected_config: Dict[str, Any] = {
            "prometheus": {
                "configs": [
                    {
                        "name": "send_remote_write",
                        "remote_write": [
                            {"url": "http://1.1.1.2:9090/api/v1/write"},
                            {"url": "http://1.1.1.1:9090/api/v1/write"},
                        ],
                        "scrape_configs": [SELF_MONITORING_SCRAPE],
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

        mock_restart.assert_called_once_with("agent")
        mock_restart.reset_mock()

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        self.assertEqual(
            config["prometheus"]["configs"][0]["remote_write"],
            [{"url": "http://1.1.1.1:9090/api/v1/write"}],
        )

        # Test scale to zero
        self.harness.remove_relation_unit(rel_id, "prometheus/0")

        mock_restart.assert_called_once_with("agent")
        mock_restart.reset_mock()

        config = yaml.safe_load(agent_container.pull("/etc/agent/agent.yaml").read())

        self.assertEqual(config["prometheus"]["configs"][0]["remote_write"], [])

    @patch.object(Container, "restart")
    def test_scrape_without_remote_write_configuration(self, mock_restart: MagicMock):
        mock_restart.restart.return_value = True
        agent_container = self.harness.charm.unit.get_container("agent")

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
        self.assertListEqual(
            config["prometheus"]["configs"],
            [
                {
                    "name": "send_remote_write",
                    "remote_write": [],
                    "scrape_configs": [SELF_MONITORING_SCRAPE],
                }
            ] 
        )

        mock_restart.assert_called_once_with("agent")
        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("no related Prometheus remote-write")
        )

    def test__cli_args(self):
        expected = "-config.file=/etc/agent/agent.yaml -prometheus.wal-directory=/tmp/agent/data"
        self.assertEqual(self.harness.charm._cli_args(), expected)

    @patch.object(Container, "restart")
    def test__on_loki_push_api_endpoint_joined(self, mock_restart: MagicMock):
        """Test Loki config is in config file when LokiPushApiEndpointJoined is fired."""
        mock_restart.restart.return_value = True
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
        mock_restart.assert_called_once_with("agent")

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
        self.harness.charm._container.restart = Mock(side_effect=GrafanaAgentReloadError)
        self.harness.charm._update_config()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("could not reload configuration")
        )
