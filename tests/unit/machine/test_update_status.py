# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import tempfile
import unittest
from unittest.mock import patch

from ops.testing import Harness

from charm import GrafanaAgentMachineCharm as GrafanaAgentCharm


class TestUpdateStatus(unittest.TestCase):
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
        self.harness.charm.on.update_status.emit()

    def test_with_relations(self):
        # self.relation_id = self.harness.add_relation("alerting", "otherapp")
        # self.harness.add_relation_unit(self.relation_id, "otherapp/0")
        pass
