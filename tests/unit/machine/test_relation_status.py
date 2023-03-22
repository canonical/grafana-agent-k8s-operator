# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import tempfile
import unittest
from unittest.mock import patch

from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import GrafanaAgentMachineCharm as GrafanaAgentCharm


class TestRelationStatus(unittest.TestCase):
    def setUp(self, *unused):
        patcher = patch.object(GrafanaAgentCharm, "_agent_version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        temp_config_path = tempfile.mkdtemp() + "/grafana-agent.yaml"
        # otherwise will attempt to write to /etc/grafana-agent.yaml
        patcher = patch("grafana_agent.CONFIG_PATH", temp_config_path)
        self.config_path_mock = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch("charm.snap")
        self.mock_snap = patcher.start()
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
        # WHEN an incoming relation is added
        rel_id = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.add_relation_unit(rel_id, "grafana-agent/0")

        # THEN the charm goes into blocked status
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        # AND WHEN all the necessary outgoing relations are added
        for outgoing in ["send-remote-write", "logging-consumer", "grafana-dashboards-provider"]:
            # Before the relation is added, the charm is still in blocked status
            self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

            rel_id = self.harness.add_relation(outgoing, "grafana-agent")
            self.harness.add_relation_unit(rel_id, "grafana-agent/0")

        # THEN the charm goes into active status
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)
