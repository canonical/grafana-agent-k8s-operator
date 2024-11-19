import pytest
from ops.testing import Context

from charm import GrafanaAgentK8sCharm


@pytest.fixture
def ctx():
    yield Context(GrafanaAgentK8sCharm)
