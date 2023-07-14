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
from helpers import FakeProcessVersionCheck
from ops.model import ActiveStatus, Container
from ops.testing import Harness

from charm import (  # isort: skip <- needed because charm.py does not always exist
    GrafanaAgentK8sCharm,
)

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

CERTS_RELATION_DATA = """[{"certificate": "-----BEGIN CERTIFICATE-----\nMIIDRDCCAiygAwIBAgIUPf3TRo7siuI9UP63UKsRF/4sUakwDQYJKoZIhvcNAQEL\nBQAwOTELMAkGA1UEBhMCVVMxKjAoBgNVBAMMIXNlbGYtc2lnbmVkLWNlcnRpZmlj\nYXRlcy1vcGVyYXRvcjAeFw0yMzA3MTMyMzM2MzdaFw0yNDA3MTIyMzM2MzdaMEEx\nEDAOBgNVBAMMB2FnZW50LzAxLTArBgNVBC0MJGJhMjk3MDhkLTEwMTYtNGQ2OS04\nOTRjLTgwOGYxYjZkMzI5NzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEB\nAJTck0+65BgohrJYrfQJKhkqiSZ1RD3upOHd69xzXda+5SJ+tjVU8aKTrY7BMyzD\n97mmeCZMryVrwa3JuoQR2ktf4Wq7DqRjG+YKFrN+MjlXu5ljTNvDZUheteahVUr9\nPDB67zgrhgc8TgorcESFlLSVQOQrMx3BEPN+PSFDqUme+0zQ5G9qCAY785ikAn7J\nGwd2tONYvrG1jA1rRw8SsF6CVZsgFgbHpfaj4Oq+yygwHXA1i0s7rf9DlUxrYaZC\nth2TzEPV9Iu0HNrJzWHJxDpeOvTptSZs5mBKSgCVW9nIaIuPWj8sEwKW9YVVlNEx\ngyjHLST4o340lKVqk2qXXE0CAwEAAaM8MDowOAYDVR0RBDEwL4ItYWdlbnQtMC5h\nZ2VudC1lbmRwb2ludHMubG1hLnN2Yy5jbHVzdGVyLmxvY2FsMA0GCSqGSIb3DQEB\nCwUAA4IBAQA8sD4zDFp0+cmv6acbSWiAVn/qZBcz0qpqmOqeUwd1IvcsczOwSzq5\n8Cf1TCJuqJFiZgyiAVNRXF8MxNXrYYB/LI5L52AeAwsv6Fpo+x8tqkzNwbpY+2aA\n1Q2Toc5/mCCSH9rzsznCjHnR1yUcEt/CzI9wfwdH0F5v5u7onrx0XXtnEiDTQIDV\nPQxGlI2xPdisqdLmFZgCjOpANRfAiBnQY1pLkH3rwHWHDsvb1jTy8UEpzYINu0vd\nogI1GMccHAq4MM7tRjmSuOL9XqgTEEvSJeJDSexDe0iWC3AYCat79tUV9gGfpkK/\nA+GdAqYgyk2tL0iL4WTIkg0t52pgkXPf\n-----END CERTIFICATE-----", "certificate_signing_request": "-----BEGIN CERTIFICATE REQUEST-----\nMIIC0TCCAbkCAQAwQTEQMA4GA1UEAwwHYWdlbnQvMDEtMCsGA1UELQwkYmEyOTcw\nOGQtMTAxNi00ZDY5LTg5NGMtODA4ZjFiNmQzMjk3MIIBIjANBgkqhkiG9w0BAQEF\nAAOCAQ8AMIIBCgKCAQEAlNyTT7rkGCiGslit9AkqGSqJJnVEPe6k4d3r3HNd1r7l\nIn62NVTxopOtjsEzLMP3uaZ4JkyvJWvBrcm6hBHaS1/harsOpGMb5goWs34yOVe7\nmWNM28NlSF615qFVSv08MHrvOCuGBzxOCitwRIWUtJVA5CszHcEQ8349IUOpSZ77\nTNDkb2oIBjvzmKQCfskbB3a041i+sbWMDWtHDxKwXoJVmyAWBsel9qPg6r7LKDAd\ncDWLSzut/0OVTGthpkK2HZPMQ9X0i7Qc2snNYcnEOl469Om1JmzmYEpKAJVb2cho\ni49aPywTApb1hVWU0TGDKMctJPijfjSUpWqTapdcTQIDAQABoEswSQYJKoZIhvcN\nAQkOMTwwOjA4BgNVHREEMTAvgi1hZ2VudC0wLmFnZW50LWVuZHBvaW50cy5sbWEu\nc3ZjLmNsdXN0ZXIubG9jYWwwDQYJKoZIhvcNAQELBQADggEBAEc+2yAnfUXukCFg\nuXuS2sqRZpA9WOZufLv8DIW3MpN2fgCqWLwzmO80IqsU24hyrzKjfKkyar8Hne04\nAAUfQvGeFGH9Fz289aa8harg5vhIp+3CbqxM9lagKF84/FSbF+wn4hlQqt/PhklD\nf3vngz9VoGPu3Ev4/385opGF9bAUaSJReE5ebWZEYfAbHi0n7vH+qYuCuhczxUYk\nRgyBtge/CwNd55iqbXy3LsbEKA9CIemyZ2Wq4Nxr5XfiPB8TXfPBYy++IIBfexMQ\nqqSIIXWuO8484e28CZCa9xzspsEy0ejfdXuxhXxTqWbRdOWQBK62D5K6rk9c4sTa\nypD7TIU=\n-----END CERTIFICATE REQUEST-----", "ca": "-----BEGIN CERTIFICATE-----\nMIIDVzCCAj+gAwIBAgIURIhdtuPZiz2sebg5YgDSDoJRcnwwDQYJKoZIhvcNAQEL\nBQAwOTELMAkGA1UEBhMCVVMxKjAoBgNVBAMMIXNlbGYtc2lnbmVkLWNlcnRpZmlj\nYXRlcy1vcGVyYXRvcjAeFw0yMzA3MTMyMzI1MDhaFw0yNDA3MTIyMzI1MDhaMDkx\nCzAJBgNVBAYTAlVTMSowKAYDVQQDDCFzZWxmLXNpZ25lZC1jZXJ0aWZpY2F0ZXMt\nb3BlcmF0b3IwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCllekttoc9\nFuO4byyyemRw+Jb0ptfeFNX4qXPhl/H3TIJkkOk9LX0AJr/0sIICfqYp9IBvcyaR\n7ECHuZsQUGKq3UR4DCmDwprjfBAA/7tk0cbuORPeBOoAJLz8/ubllbJnaCCdW+bb\nhB5w+0IZ2dtIPNWc3TAwyjv6JkwDrR197+ievZ8rFFE/0v+40baMA+tMdAgB4EuE\nvnDIZ/0Js0Nv6Lkc8Ga+3BJieH9eSC6LDDXlWv5u59NrjCbr7HLZxyqSISavFFnQ\n08k/luuQRfx4an0qjOOPNk6k2eDsRTR2Ov/aiwkw4mI+IOKP5SVEgVKJx80XXXCu\nAcliBMpJ2PnhAgMBAAGjVzBVMB8GA1UdDgQYBBYEFFz/sE6F0zH4E6ahq5BEx2bY\no0GdMCEGA1UdIwQaMBiAFgQUXP+wToXTMfgTpqGrkETHZtijQZ0wDwYDVR0TAQH/\nBAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAQEAUNqmTqlJhUEW+1S1cAMwtkLGZ9S9\nHIZ/u6TeJKx9NvDYBW/dJzMkfNC5lKT18Hyat7Qrnmpa+cXKra+VPt/18eRylZgI\nR5UpTaaZF48jkisYcxm7hGoR7G3vNd1cUKweRuDR0bRrJOZ9RQacsaWSFMX2Afv/\nQl0XsvCUHXL1R3f2eEquOFlOqd4YnlPA5b0qo20ezDYbOjKS648G8t6r0JvNXU1G\nHRcCfSN3uMuP7dEYylzP/aECFMcP/wdl9GyuOJhyNCmucQRPiNM5RQp71CmDXpUN\nFP+svfCC/swN8ZSxqYxubVL/kyUAsPk81IO7zOrbdd9gJEuRKWoWa/eWxw==\n-----END CERTIFICATE-----", "chain": ["-----BEGIN CERTIFICATE-----\nMIIDVzCCAj+gAwIBAgIURIhdtuPZiz2sebg5YgDSDoJRcnwwDQYJKoZIhvcNAQEL\nBQAwOTELMAkGA1UEBhMCVVMxKjAoBgNVBAMMIXNlbGYtc2lnbmVkLWNlcnRpZmlj\nYXRlcy1vcGVyYXRvcjAeFw0yMzA3MTMyMzI1MDhaFw0yNDA3MTIyMzI1MDhaMDkx\nCzAJBgNVBAYTAlVTMSowKAYDVQQDDCFzZWxmLXNpZ25lZC1jZXJ0aWZpY2F0ZXMt\nb3BlcmF0b3IwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCllekttoc9\nFuO4byyyemRw+Jb0ptfeFNX4qXPhl/H3TIJkkOk9LX0AJr/0sIICfqYp9IBvcyaR\n7ECHuZsQUGKq3UR4DCmDwprjfBAA/7tk0cbuORPeBOoAJLz8/ubllbJnaCCdW+bb\nhB5w+0IZ2dtIPNWc3TAwyjv6JkwDrR197+ievZ8rFFE/0v+40baMA+tMdAgB4EuE\nvnDIZ/0Js0Nv6Lkc8Ga+3BJieH9eSC6LDDXlWv5u59NrjCbr7HLZxyqSISavFFnQ\n08k/luuQRfx4an0qjOOPNk6k2eDsRTR2Ov/aiwkw4mI+IOKP5SVEgVKJx80XXXCu\nAcliBMpJ2PnhAgMBAAGjVzBVMB8GA1UdDgQYBBYEFFz/sE6F0zH4E6ahq5BEx2bY\no0GdMCEGA1UdIwQaMBiAFgQUXP+wToXTMfgTpqGrkETHZtijQZ0wDwYDVR0TAQH/\nBAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAQEAUNqmTqlJhUEW+1S1cAMwtkLGZ9S9\nHIZ/u6TeJKx9NvDYBW/dJzMkfNC5lKT18Hyat7Qrnmpa+cXKra+VPt/18eRylZgI\nR5UpTaaZF48jkisYcxm7hGoR7G3vNd1cUKweRuDR0bRrJOZ9RQacsaWSFMX2Afv/\nQl0XsvCUHXL1R3f2eEquOFlOqd4YnlPA5b0qo20ezDYbOjKS648G8t6r0JvNXU1G\nHRcCfSN3uMuP7dEYylzP/aECFMcP/wdl9GyuOJhyNCmucQRPiNM5RQp71CmDXpUN\nFP+svfCC/swN8ZSxqYxubVL/kyUAsPk81IO7zOrbdd9gJEuRKWoWa/eWxw==\n-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----\nMIIDRDCCAiygAwIBAgIUPf3TRo7siuI9UP63UKsRF/4sUakwDQYJKoZIhvcNAQEL\nBQAwOTELMAkGA1UEBhMCVVMxKjAoBgNVBAMMIXNlbGYtc2lnbmVkLWNlcnRpZmlj\nYXRlcy1vcGVyYXRvcjAeFw0yMzA3MTMyMzM2MzdaFw0yNDA3MTIyMzM2MzdaMEEx\nEDAOBgNVBAMMB2FnZW50LzAxLTArBgNVBC0MJGJhMjk3MDhkLTEwMTYtNGQ2OS04\nOTRjLTgwOGYxYjZkMzI5NzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEB\nAJTck0+65BgohrJYrfQJKhkqiSZ1RD3upOHd69xzXda+5SJ+tjVU8aKTrY7BMyzD\n97mmeCZMryVrwa3JuoQR2ktf4Wq7DqRjG+YKFrN+MjlXu5ljTNvDZUheteahVUr9\nPDB67zgrhgc8TgorcESFlLSVQOQrMx3BEPN+PSFDqUme+0zQ5G9qCAY785ikAn7J\nGwd2tONYvrG1jA1rRw8SsF6CVZsgFgbHpfaj4Oq+yygwHXA1i0s7rf9DlUxrYaZC\nth2TzEPV9Iu0HNrJzWHJxDpeOvTptSZs5mBKSgCVW9nIaIuPWj8sEwKW9YVVlNEx\ngyjHLST4o340lKVqk2qXXE0CAwEAAaM8MDowOAYDVR0RBDEwL4ItYWdlbnQtMC5h\nZ2VudC1lbmRwb2ludHMubG1hLnN2Yy5jbHVzdGVyLmxvY2FsMA0GCSqGSIb3DQEB\nCwUAA4IBAQA8sD4zDFp0+cmv6acbSWiAVn/qZBcz0qpqmOqeUwd1IvcsczOwSzq5\n8Cf1TCJuqJFiZgyiAVNRXF8MxNXrYYB/LI5L52AeAwsv6Fpo+x8tqkzNwbpY+2aA\n1Q2Toc5/mCCSH9rzsznCjHnR1yUcEt/CzI9wfwdH0F5v5u7onrx0XXtnEiDTQIDV\nPQxGlI2xPdisqdLmFZgCjOpANRfAiBnQY1pLkH3rwHWHDsvb1jTy8UEpzYINu0vd\nogI1GMccHAq4MM7tRjmSuOL9XqgTEEvSJeJDSexDe0iWC3AYCat79tUV9gGfpkK/\nA+GdAqYgyk2tL0iL4WTIkg0t52pgkXPf\n-----END CERTIFICATE-----"]}]"""


@patch.object(Container, "restart", new=lambda x, y: True)
@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestScrapeConfiguration(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
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
        }

        config = yaml.safe_load(agent_container.pull("/etc/grafana-agent.yaml").read())

        self.assertEqual(
            DeepDiff(expected_config, self.harness.charm._generate_config(), ignore_order=True), {}
        )
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

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

    def test__cli_args(self):
        expected = "-config.file=/etc/grafana-agent.yaml"
        self.assertEqual(self.harness.charm._cli_args(), expected)

    def test__cli_args_with_tls(self):
        rel_id = self.harness.add_relation("certificates", "certs")
        self.harness.add_relation_unit(rel_id, "certs/0")
        expected = "-config.file=/etc/grafana-agent.yaml -server.http.enable-tls -server.grpc.enable-tls"
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
        rel_id = self.harness.add_relation("certificates", "certs")
        self.harness.add_relation_unit(rel_id, "certs/0")
        self.harness.update_relation_data(rel_id, "certs", {"certificates": CERTS_RELATION_DATA})
        configs = self.harness.charm._loki_config
        for config in configs:
            for scrape_config in config.get("scrape_configs", []):
                if scrape_config.get("loki_push_api"):
                    self.assertIn("http_tls_config", scrape_config["loki_push_api"]["server"])
                    self.assertIn("grpc_tls_config", scrape_config["loki_push_api"]["server"])
