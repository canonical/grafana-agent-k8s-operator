# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import MagicMock, patch

import responses
from ops.model import ActiveStatus, BlockedStatus, Container
from ops.testing import Harness

from charm import GrafanaAgentOperatorCharm


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


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(GrafanaAgentOperatorCharm)
        self.addCleanup(self.harness.cleanup)
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

        # Two configs pushed out, one per unit added
        self.assertEqual(2, len(mock_push.mock_calls))
        # TODO Check content pushed

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

        # One config pushed out
        self.assertEqual(1, len(mock_push.mock_calls))
        # TODO Check content pushed

        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("no related Prometheus remote-write")
        )
