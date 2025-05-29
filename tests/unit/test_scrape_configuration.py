# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import ops.testing
import responses
import yaml
from deepdiff import DeepDiff  # type: ignore
from helpers import FakeProcessVersionCheck, k8s_resource_multipatch, patch_lightkube_client
from ops.model import ActiveStatus, Container
from ops.testing import Harness

from charm import (  # isort: skip <- needed because charm.py does not always exist
    GrafanaAgentK8sCharm,
)

ops.testing.SIMULATE_CAN_CONNECT = True  # type: ignore

SAMPLE_UUID = "20ed9535-c14a-4ec9-a250-fd7a6414feb5"

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
        "replacement": f"juju_lma_{SAMPLE_UUID}_grafana-agent-k8s_self-monitoring",
    },
    {
        "target_label": "instance",
        "regex": "(.*)",
        "replacement": f"lma_{SAMPLE_UUID}_grafana-agent-k8s_grafana-agent-k8s/0",
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
        "replacement": SAMPLE_UUID,
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

CERTS_RELATION_DATA = """[{"certificate": "-----BEGIN CERTIFICATE-----foobarcert-----END CERTIFICATE-----", "certificate_signing_request": "-----BEGIN CERTIFICATE REQUEST-----foobarcsr-----END CERTIFICATE REQUEST-----", "ca": "-----BEGIN CERTIFICATE-----foobarca-----END CERTIFICATE-----", "chain": ["-----BEGIN CERTIFICATE-----foobarchain0-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----foobarchain1-----END CERTIFICATE-----"]}]"""


@patch.object(Container, "restart", new=lambda x, y: True)
@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestScrapeConfiguration(unittest.TestCase):
    @patch_lightkube_client
    @k8s_resource_multipatch
    @patch("grafana_agent.GrafanaAgentCharm.charm_dir", Path("/"))
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
        self.harness.set_model_info(name="lma", uuid=SAMPLE_UUID)
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

        # Add incoming relation
        rel_incoming_id = self.harness.add_relation("metrics-endpoint", "agent")
        self.harness.add_relation_unit(rel_incoming_id, "agent/0")

        rel_id = self.harness.add_relation("send-remote-write", "prometheus")

        self.harness.add_relation_unit(rel_id, "prometheus/0")
        self.harness.update_relation_data(
            rel_id,
            "prometheus/0",
            {
                "remote_write": json.dumps(
                    {
                        "url": "http://1.1.1.1:9090/api/v1/write",
                        "tls_config": {"insecure_skip_verify": False},
                    }
                )
            },
        )

        self.harness.add_relation_unit(rel_id, "prometheus/1")
        self.harness.update_relation_data(
            rel_id,
            "prometheus/1",
            {
                "remote_write": json.dumps(
                    {
                        "url": "http://1.1.1.2:9090/api/v1/write",
                        "tls_config": {"insecure_skip_verify": False},
                    }
                )
            },
        )

        expected_config: Dict[str, Any] = {
            "integrations": {
                "agent": {
                    "enabled": True,
                    "relabel_configs": REWRITE_CONFIGS,
                },
                "prometheus_remote_write": [
                    {
                        "url": "http://1.1.1.2:9090/api/v1/write",
                        "tls_config": {"insecure_skip_verify": False},
                    },
                    {
                        "url": "http://1.1.1.1:9090/api/v1/write",
                        "tls_config": {"insecure_skip_verify": False},
                    },
                ],
            },
            "metrics": {
                "wal_directory": "/tmp/agent/data",
                "configs": [
                    {
                        "name": "agent_scraper",
                        "remote_write": [
                            {
                                "url": "http://1.1.1.2:9090/api/v1/write",
                                "tls_config": {"insecure_skip_verify": False},
                            },
                            {
                                "url": "http://1.1.1.1:9090/api/v1/write",
                                "tls_config": {"insecure_skip_verify": False},
                            },
                        ],
                        "scrape_configs": [],
                    }
                ],
            },
            "server": {"log_level": "info"},
            "logs": {},
            "traces": {},
        }

        config = yaml.safe_load(agent_container.pull("/etc/grafana-agent.yaml").read())

        self.assertEqual(
            DeepDiff(expected_config, self.harness.charm._generate_config(), ignore_order=True), {}
        )
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

        # Test scale down
        self.harness.remove_relation_unit(rel_id, "prometheus/1")

        config = yaml.safe_load(agent_container.pull("/etc/grafana-agent.yaml").read())

        self.assertEqual(
            config["integrations"]["prometheus_remote_write"],
            [
                {
                    "url": "http://1.1.1.1:9090/api/v1/write",
                    "tls_config": {"insecure_skip_verify": False},
                }
            ],
        )
        self.assertEqual(
            config["metrics"]["configs"][0]["remote_write"],
            [
                {
                    "url": "http://1.1.1.1:9090/api/v1/write",
                    "tls_config": {"insecure_skip_verify": False},
                }
            ],
        )

        # Test scale to zero
        self.harness.remove_relation_unit(rel_id, "prometheus/0")

        config = yaml.safe_load(agent_container.pull("/etc/grafana-agent.yaml").read())

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

        config = yaml.safe_load(agent_container.pull("/etc/grafana-agent.yaml").read())
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

    def test_cli_args(self):
        expected = "-config.file=/etc/grafana-agent.yaml"
        self.assertEqual(self.harness.charm._cli_args(), expected)

    def test_cli_args_with_tls(self):
        rel_id = self.harness.add_relation("certificates", "certs")
        self.harness.add_relation_unit(rel_id, "certs/0")
        expected = (
            "-config.file=/etc/grafana-agent.yaml -server.http.enable-tls -server.grpc.enable-tls"
        )
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
            "configs": [
                {
                    "name": "push_api_server",
                    "clients": [
                        {
                            "url": "http://loki0:3100:/loki/api/v1/push",
                            "tls_config": {"insecure_skip_verify": False},
                        },
                        {
                            "url": "http://loki1:3100:/loki/api/v1/push",
                            "tls_config": {"insecure_skip_verify": False},
                        },
                    ],
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
                },
            ],
            "positions_directory": "/run/grafana-agent-positions",
        }
        self.assertEqual(
            DeepDiff(expected, self.harness.charm._loki_config, ignore_order=True), {}
        )

        self.harness.remove_relation(rel_id)
        self.assertEqual({}, self.harness.charm._loki_config)

    def test_loki_config_with_tls(self):
        self.harness.handle_exec("agent", ["update-ca-certificates"], result=0)
        rel_id = self.harness.add_relation("certificates", "certs")
        self.harness.add_relation_unit(rel_id, "certs/0")
        self.harness.update_relation_data(rel_id, "certs", {"certificates": CERTS_RELATION_DATA})
        configs = self.harness.charm._loki_config
        for config in configs:
            for scrape_config in config.get("scrape_configs", []):  # pyright: ignore
                if scrape_config.get("loki_push_api"):
                    self.assertIn("http_tls_config", scrape_config["loki_push_api"]["server"])
                    self.assertIn("grpc_tls_config", scrape_config["loki_push_api"]["server"])
