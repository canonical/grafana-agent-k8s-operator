# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock

import yaml
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import GrafanaAgentOperatorCharm, GrafanaAgentReloadError


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(GrafanaAgentOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin_with_initial_hooks()

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
        expected = {
            "integrations": {"agent": {"enabled": True}, "prometheus_remote_write": []},
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
            "integrations": {"agent": {"enabled": True}, "prometheus_remote_write": []},
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
        self.assertDictEqual(yaml.safe_load(self.harness.charm._config_file()), expected)

    def test__update_config_pebble_not_ready(self):
        self.harness.charm._container.can_connect = Mock(return_value=False)
        self.harness.charm._update_config()
        self.assertIsInstance(self.harness.charm.unit.status, WaitingStatus)

    def test__update_config_pebble_ready(self):
        self.harness.charm._container.can_connect = Mock(return_value=True)
        self.harness.charm._container.pull = Mock(return_value="")
        self.harness.charm._container.push = Mock(return_value=True)
        self.harness.charm._reload_config = Mock(return_value=True)
        self.harness.charm._update_config()
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        self.harness.charm._reload_config = Mock(side_effect=GrafanaAgentReloadError)
        self.harness.charm._update_config()
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)
