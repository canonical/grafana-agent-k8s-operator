import shutil
from pathlib import Path, PosixPath

import pytest

from tests.scenario.helpers import CHARM_ROOT


class Vroot(PosixPath):
    def clean(self) -> None:
        shutil.rmtree(self)
        shutil.copytree(CHARM_ROOT / "src", self / "src")


@pytest.fixture
def vroot(tmp_path) -> Path:
    vroot = Vroot(str(tmp_path.absolute()))
    vroot.clean()
    return vroot
