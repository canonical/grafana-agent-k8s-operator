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


def pull_empty_fake_file(self, _):
    return FakeFile("")


class FakeFile:
    def __init__(self, content=""):
        self.content = content

    def read(self, *args, **kwargs):
        return self.content


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
    def setUp(self):
        self.harness = Harness(GrafanaAgentOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_model_info(name="lma", uuid="1234567890")
        self.harness.set_leader(True)
        self.harness.begin()

    @responses.activate
    @patch.object(Container, "pull", new=pull_empty_fake_file)
    @patch.object(Container, "push")
    def test_remote_write_configuration(self, mock_push: MagicMock):
        mock_push.push.return_value = None

        responses.add(
            responses.POST,
            "http://localhost/-/reload",
            status=200,
        )

        rel_id = self.harness.add_relation("prometheus-remote-write", "prometheus")

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

        path, content = mock_push.call_args[0]
        content = yaml.safe_load(content)
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
        }
        self.assertEqual(path, "/etc/agent/agent.yaml")

        self.assertEqual(
            DeepDiff(content["integrations"], expected_config["integrations"], ignore_order=True),
            {},
        )
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

    @responses.activate
    @patch.object(Container, "pull", new=pull_empty_fake_file)
    @patch.object(Container, "push")
    def test_scrape_without_remote_write_configuration(self, mock_push: MagicMock):
        mock_push.push.return_value = None

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

        path, content = mock_push.call_args[0]
        self.assertEqual(path, "/etc/agent/agent.yaml")
        self.assertDictEqual(
            yaml.safe_load(content)["integrations"],
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
    @patch.object(Container, "pull", new=pull_empty_fake_file)
    @patch.object(Container, "push")
    def test__on_loki_push_api_endpoint_joined(self, mock_push: MagicMock):
        """Test Loki config is in config file when LokiPushApiEndpointJoined is fired."""
        self.harness.charm._loki_consumer = Mock()
        self.harness.charm._loki_consumer.loki_push_api = "http://loki:3100:/loki/api/v1/push"

        handle = Handle(None, "kind", "Key")
        event = LokiPushApiEndpointJoined(handle)
        self.harness.charm._on_loki_push_api_endpoint_joined(event)

        path, content = mock_push.call_args[0]

        self.assertEqual(path, "/etc/agent/agent.yaml")
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
        self.assertDictEqual(yaml.safe_load(content)["loki"], expected)

    @responses.activate
    @patch.object(Container, "pull", new=pull_empty_fake_file)
    @patch.object(Container, "push")
    def test__on_loki_push_api_endpoint_departed(self, mock_push: MagicMock):
        """Test Loki config is not in config file when LokiPushApiEndpointDeparted is fired."""
        self.harness.charm._loki_consumer = Mock()
        self.harness.charm._loki_consumer.loki_push_api = "http://loki:3100:/loki/api/v1/push"

        handle = Handle(None, "kind", "Key")
        event = LokiPushApiEndpointDeparted(handle)
        self.harness.charm._on_loki_push_api_endpoint_departed(event)

        path, content = mock_push.call_args[0]

        self.assertEqual(path, "/etc/agent/agent.yaml")
        self.assertTrue(yaml.safe_load(content)["loki"] == {})

    def test__update_config_pebble_ready(self):
        self.harness.charm._container.can_connect = Mock(return_value=True)
        self.harness.charm._container.pull = Mock(return_value="")
        self.harness.charm._container.push = Mock(return_value=True)
        self.harness.charm._reload_config = Mock(return_value=True)
        self.harness.charm._update_config()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        self.harness.charm._reload_config = Mock(side_effect=GrafanaAgentReloadError)
        self.harness.charm._update_config()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("could not reload configuration")
        )
