# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import tempfile
import unittest
from unittest.mock import patch

from charm import GrafanaAgentMachineCharm as GrafanaAgentCharm
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness


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
        # THEN status is "blocked"
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        # AND WHEN "update-status" fires
        self.harness.charm.on.update_status.emit()
        # THEN status is still "blocked"
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

    def test_cos_agent_with_relations(self):
        # WHEN an incoming relation is added
        rel_id = self.harness.add_relation("cos-agent", "grafana-agent")
        self.harness.add_relation_unit(rel_id, "grafana-agent/0")

        # THEN the charm goes into blocked status
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        # AND WHEN at least one of the necessary outgoing relations is added
        for outgoing in ["send-remote-write", "logging-consumer", "grafana-dashboards-provider"]:
            rel_id = self.harness.add_relation(outgoing, "grafana-agent")
            self.harness.add_relation_unit(rel_id, "grafana-agent/0")

            # THEN the charm goes into active status when one mandatory relation is added
            self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        # AND WHEN we remove one of the mandatory relations
        self.harness.remove_relation(rel_id)

        # THEN the charm keeps into active status
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

    def test_juju_info_with_relations(self):
        # WHEN an incoming relation is added
        rel_id = self.harness.add_relation("juju-info", "grafana-agent")
        self.harness.add_relation_unit(rel_id, "grafana-agent/0")

        # THEN the charm goes into blocked status
        self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        # AND WHEN all the necessary outgoing relations are added
        for outgoing in ["send-remote-write", "logging-consumer"]:
            rel_id = self.harness.add_relation(outgoing, "grafana-agent")
            self.harness.add_relation_unit(rel_id, "grafana-agent/0")

        # THEN the charm goes into active status
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)
