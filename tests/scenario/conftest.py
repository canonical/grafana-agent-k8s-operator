import shutil
from pathlib import Path

import pytest

from tests.scenario.helpers import CHARM_ROOT


@pytest.fixture
def vroot(tmp_path) -> Path:
    shutil.copytree(CHARM_ROOT / "src", tmp_path / "src")
    return tmp_path
