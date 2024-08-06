import shutil
from pathlib import Path, PosixPath

import pytest

CHARM_ROOT = Path(__file__).parent.parent.parent

class Vroot(PosixPath):
    def clean(self) -> None:
        shutil.rmtree(self)
        shutil.copytree(CHARM_ROOT / "src", self / "src")


@pytest.fixture
def vroot(tmp_path) -> Path:
    vroot = Vroot(str(tmp_path.absolute()))
    vroot.clean()
    return vroot
