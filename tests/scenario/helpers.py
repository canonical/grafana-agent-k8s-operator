# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import inspect
from pathlib import Path

import yaml

import k8s_charm
import machine_charm

CHARM_ROOT = Path(__file__).parent.parent.parent


def get_charm_meta(charm_type) -> dict:
    if charm_type is machine_charm.GrafanaAgentMachineCharm:
        fname = "machine_metadata"
    elif charm_type is k8s_charm.GrafanaAgentK8sCharm:
        fname = "k8s_metadata"
    else:
        raise TypeError(charm_type)

    charm_source_path = Path(inspect.getfile(charm_type))
    charm_root = charm_source_path.parent.parent

    raw_meta = (charm_root / fname).with_suffix(".yaml").read_text()
    return yaml.safe_load(raw_meta)
