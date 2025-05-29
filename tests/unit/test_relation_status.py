# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from helpers import k8s_resource_multipatch
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import GrafanaAgentK8sCharm as GrafanaAgentCharm


class TestRelationStatus(unittest.TestCase):
    @k8s_resource_multipatch
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
        # THEN status is "blocked"
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        # AND WHEN "update-status" fires
        self.harness.charm.on.update_status.emit()
        # THEN status is still "blocked"
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

    def test_with_relations(self):
        for incoming, outgoing in [
            ("logging-provider", "logging-consumer"),
            ("metrics-endpoint", "send-remote-write"),
            ("grafana-dashboards-consumer", "grafana-dashboards-provider"),
        ]:
            with self.subTest(incoming=incoming, outgoing=outgoing):
                # WHEN an incoming relation is added
                rel_incoming_id = self.harness.add_relation(incoming, "incoming")
                self.harness.add_relation_unit(rel_incoming_id, "incoming/0")
                self.harness.update_relation_data(
                    rel_incoming_id, "incoming/0", {"sample": "value"}
                )

                # THEN the charm goes into blocked status
                self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

                # AND WHEN an appropriate outgoing relation is added
                rel_outgoing_id = self.harness.add_relation(outgoing, "outgoing")
                self.harness.add_relation_unit(rel_outgoing_id, "outgoing/0")

                # THEN the charm goes into active status
                self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

                # Remove incoming relation (cleanup for the next subTest).
                self.harness.remove_relation(rel_incoming_id)
