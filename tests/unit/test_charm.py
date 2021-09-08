# Copyright 2021 Dylan Stephano-Shachter
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest

from ops.testing import Harness

from charm import GrafanaAgentOperatorCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(GrafanaAgentOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin_with_initial_hooks()

    def test_pass(self):
        pass
