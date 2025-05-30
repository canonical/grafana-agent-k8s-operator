# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch


class FakeProcessVersionCheck:
    def __init__(self, args):
        pass

    def wait_output(self):
        return ("v0.1.0", "")


k8s_resource_multipatch = patch.multiple(
    "charms.observability_libs.v0.kubernetes_compute_resources_patch.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
)


def patch_lightkube_client(func):
    """Decorator that patches GenericSyncClient to avoid real access to Kubernetes."""
    return patch("lightkube.core.client.GenericSyncClient", new=MagicMock())(func)

