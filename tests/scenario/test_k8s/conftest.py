# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def patch_all():
    with patch("charm.KubernetesServicePatch", lambda x, y: None):
        yield
