# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from charm import GrafanaAgentK8sCharm as GrafanaAgentCharm
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness


@patch("charm.KubernetesServicePatch", lambda *_, **__: None)
class TestRelationStatus(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def setUp(self, *unused):
        patcher = patch.object(GrafanaAgentCharm, "_agent_version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        self.harness = Harness(GrafanaAgentCharm)
        self.harness.set_model_name(self.__class__.__name__)

        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    def test_no_relations(self):
        # GIVEN no relations joined (see SetUp)
        # WHEN the charm starts (see SetUp)
        # THEN status is "active"
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        # AND WHEN "update-status" fires
        self.harness.charm.on.update_status.emit()
        # THEN status is still "active"
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

    def test_with_relations(self):
        for incoming, outgoing in [
            ("logging-provider", "logging-consumer"),
            ("metrics-endpoint", "send-remote-write"),
            ("grafana-dashboards-consumer", "grafana-dashboards-provider"),
        ]:
            with self.subTest(incoming=incoming, outgoing=outgoing):
                # WHEN an incoming relation is added
                rel_id = self.harness.add_relation(incoming, "grafana-agent")
                self.harness.add_relation_unit(rel_id, "grafana-agent/0")
                self.harness.update_relation_data(rel_id, "grafana-agent/0", {"dummy": "value"})

                # THEN the charm goes into blocked status
                self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

                # AND WHEN an appropriate outgoing relation is added
                rel_id = self.harness.add_relation(outgoing, "grafana-agent")
                self.harness.add_relation_unit(rel_id, "grafana-agent/0")

                # THEN the charm goes into active status
                self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)
