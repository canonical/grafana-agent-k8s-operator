# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import MagicMock, Mock, patch

import responses
import yaml
from ops.model import ActiveStatus, BlockedStatus, Container, WaitingStatus
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
        self.harness.begin_with_initial_hooks()

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

        rel_id = self.harness.add_relation("prometheus-remote-write", "prometheus-k8s")

        self.harness.add_relation_unit(rel_id, "prometheus-k8s/0")
        self.harness.update_relation_data(
            rel_id,
            "prometheus-k8s/0",
            {
                "address": "1.1.1.1",
                "port": "9090",
            },
        )

        self.harness.add_relation_unit(rel_id, "prometheus-k8s/1")
        self.harness.update_relation_data(
            rel_id,
            "prometheus-k8s/1",
            {
                "address": "1.1.1.2",
                "port": "9090",
            },
        )

        path, content = mock_push.call_args[0]
        self.assertEqual(path, "/etc/agent/agent.yaml")
        self.assertDictEqual(
            yaml.load(content, Loader=yaml.FullLoader),
            {
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
            },
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
            yaml.load(content, Loader=yaml.FullLoader),
            {
                "integrations": {
                    "agent": {
                        "enabled": True,
                        "relabel_configs": REWRITE_CONFIGS,
                    },
                    "prometheus_remote_write": [],
                },
                "prometheus": {
                    "configs": [
                        {
                            "name": "agent_scraper",
                            "remote_write": [],
                            "scrape_configs": [],
                        }
                    ]
                },
                "server": {"log_level": "info"},
            },
        )

        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("no related Prometheus remote-write")
        )

    def test__cli_args(self):
        expected = "-config.file=/etc/agent/agent.yaml -prometheus.wal-directory=/tmp/agent/data"
        self.assertEqual(self.harness.charm._cli_args(), expected)

    def test__loki_config_empty(self):
        self.harness.charm._stored.remove_loki_config = True
        self.assertEqual(self.harness.charm._loki_config(), {})

        self.harness.charm._stored.remove_loki_config = False
        self.assertEqual(self.harness.charm._loki_config(), {})

    def test__loki_config_non_empty(self):
        self.harness.charm._loki = Mock()
        self.harness.charm._loki.loki_push_api = "http://loki:3100:/loki/api/v1/push"

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
                                "labels": {"pushserver": "loki"},
                            },
                        }
                    ],
                }
            ]
        }

        self.assertDictEqual(self.harness.charm._loki_config(), expected)

    def test__config_file_without_loki(self):
        self.maxDiff = None
        expected = {
            "integrations": {
                "agent": {
                    "enabled": True,
                    "relabel_configs": REWRITE_CONFIGS,
                },
                "prometheus_remote_write": [],
            },
            "prometheus": {
                "configs": [{"name": "agent_scraper", "remote_write": [], "scrape_configs": []}]
            },
            "server": {"log_level": "info"},
        }
        self.assertDictEqual(yaml.safe_load(self.harness.charm._config_file()), expected)

    def test__config_file_with_loki(self):
        self.harness.charm._loki = Mock()
        self.harness.charm._loki.loki_push_api = "http://loki:3100:/loki/api/v1/push"
        expected = {
            "integrations": {
                "agent": {
                    "enabled": True,
                    "relabel_configs": REWRITE_CONFIGS,
                },
                "prometheus_remote_write": [],
            },
            "prometheus": {
                "configs": [{"name": "agent_scraper", "remote_write": [], "scrape_configs": []}]
            },
            "server": {"log_level": "info"},
            "loki": {
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
                                    "labels": {"pushserver": "loki"},
                                },
                            }
                        ],
                    }
                ]
            },
        }
        self.assertDictEqual(expected, yaml.safe_load(self.harness.charm._config_file()))

    def test__update_config_pebble_not_ready(self):
        self.harness.charm._container.can_connect = Mock(return_value=False)
        self.harness.charm._update_config()
        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("waiting for agent container to start")
        )

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
