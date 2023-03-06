# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops
import yaml
from ops import pebble
from ops.model import ActiveStatus, BlockedStatus, Container
from ops.testing import Harness

from charm import GrafanaAgentK8sCharm as GrafanaAgentCharm


@patch("charm.KubernetesServicePatch", lambda *_, **__: None)
class TestUpdateStatus(unittest.TestCase):
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
        self.harness.charm.on.update_status.emit()

    def test_with_relations(self):
        # self.relation_id = self.harness.add_relation("alerting", "otherapp")
        # self.harness.add_relation_unit(self.relation_id, "otherapp/0")
        pass
