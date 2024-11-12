from ops.testing import Context

from charm import GrafanaAgentK8sCharm

import pytest


@pytest.fixture
def ctx():
    yield Context(GrafanaAgentK8sCharm)
