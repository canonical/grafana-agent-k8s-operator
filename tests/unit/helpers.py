# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch


class FakeProcessVersionCheck:
    def __init__(self, args):
        pass

    def wait_output(self):
        return ("v0.1.0", "")


k8s_resource_multipatch = patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
)
