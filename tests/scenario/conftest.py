import shutil
from pathlib import Path
from ops.testing import Context

from charm import GrafanaAgentK8sCharm

import pytest

CHARM_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def vroot(tmp_path) -> Path:
    root = Path(str(tmp_path.absolute()))
    shutil.rmtree(root)
    shutil.copytree(CHARM_ROOT / "src", root / "src")
    return root


@pytest.fixture
def ctx():
    yield Context(GrafanaAgentK8sCharm)
