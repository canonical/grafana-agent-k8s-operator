# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import pytest


@pytest.fixture
def placeholder_cfg_path(tmp_path):
    return tmp_path / "foo.yaml"
