#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import inspect
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import yaml
from charms.grafana_agent.v0.cos_agent import CosAgentProviderUnitData
from scenario import Model, PeerRelation, Relation, State, SubordinateRelation

import machine_charm

machine_meta = yaml.safe_load(
    (
        Path(inspect.getfile(machine_charm.GrafanaAgentMachineCharm)).parent.parent
        / "machine_metadata.yaml"
    ).read_text()
)


def test_snap_endpoints():
    written_path, written_text = "", ""

    def mock_write(_, path, text):
        nonlocal written_path, written_text
        written_path = path
        written_text = text

    loki_relation = Relation(
        "logging-consumer",
        remote_app_name="loki",
        remote_units_data={
            1: {"endpoint": json.dumps({"url": "http://loki1:3100/loki/api/v1/push"})}
        },
    )

    data = CosAgentProviderUnitData(
        dashboards=[],
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=["foo:bar", "oh:snap", "shameless-plug"],
    )
    cos_relation = SubordinateRelation(
        "cos-agent", primary_app_name="principal", remote_unit_data={data.KEY: data.json()}
    )

    vroot = tempfile.TemporaryDirectory()
    vroot_path = Path(vroot.name)
    vroot_path.joinpath("src", "loki_alert_rules").mkdir(parents=True)
    vroot_path.joinpath("src", "prometheus_alert_rules").mkdir(parents=True)
    vroot_path.joinpath("src", "grafana_dashboards").mkdir(parents=True)

    my_uuid = str(uuid.uuid4())

    with patch("charms.operator_libs_linux.v1.snap.SnapCache"):
        with patch("machine_charm.GrafanaAgentMachineCharm.write_file", new=mock_write):
            with patch("machine_charm.GrafanaAgentMachineCharm.is_ready", return_value=True):
                State(
                    relations=[cos_relation, loki_relation, PeerRelation("peers")],
                    model=Model(name="my-model", uuid=my_uuid),
                ).trigger(
                    event=cos_relation.changed_event,
                    charm_type=machine_charm.GrafanaAgentMachineCharm,
                    meta=machine_meta,
                    charm_root=vroot.name,
                )

    assert written_path == "/etc/grafana-agent.yaml"
    written_config = yaml.safe_load(written_text)
    assert written_config == {
        "integrations": {
            "agent": {
                "enabled": True,
                "relabel_configs": [
                    {
                        "regex": "(.*)",
                        "replacement": f"juju_my-model_{my_uuid}_grafana-agent_self-monitoring",
                        "target_label": "job",
                    },
                    {
                        "regex": "(.*)",
                        "replacement": f"my-model_{my_uuid}_principal_principal/0",
                        "target_label": "instance",
                    },
                    {
                        "replacement": "grafana-agent",
                        "source_labels": ["__address__"],
                        "target_label": "juju_charm",
                    },
                    {
                        "replacement": "my-model",
                        "source_labels": ["__address__"],
                        "target_label": "juju_model",
                    },
                    {
                        "replacement": my_uuid,
                        "source_labels": ["__address__"],
                        "target_label": "juju_model_uuid",
                    },
                    {
                        "replacement": "grafana-agent",
                        "source_labels": ["__address__"],
                        "target_label": "juju_application",
                    },
                    {
                        "replacement": "grafana-agent/0",
                        "source_labels": ["__address__"],
                        "target_label": "juju_unit",
                    },
                ],
            },
            "node_exporter": {
                "enabled": True,
                "relabel_configs": [
                    {
                        "regex": "(.*)",
                        "replacement": f"juju_my-model_{my_uuid}_grafana-agent_node-exporter",
                        "target_label": "job",
                    },
                    {
                        "regex": "(.*)",
                        "replacement": f"my-model_{my_uuid}_principal_principal/0",
                        "target_label": "instance",
                    },
                    {
                        "replacement": "my-model",
                        "source_labels": ["__address__"],
                        "target_label": "juju_model",
                    },
                    {
                        "replacement": my_uuid,
                        "source_labels": ["__address__"],
                        "target_label": "juju_model_uuid",
                    },
                    {
                        "replacement": "principal",
                        "source_labels": ["__address__"],
                        "target_label": "juju_application",
                    },
                    {
                        "replacement": "principal/0",
                        "source_labels": ["__address__"],
                        "target_label": "juju_unit",
                    },
                ],
            },
            "prometheus_remote_write": [],
        },
        "logs": {
            "configs": [
                {
                    "clients": [
                        {
                            "tls_config": {"insecure_skip_verify": None},
                            "url": "http://loki1:3100/loki/api/v1/push",
                        }
                    ],
                    "name": "push_api_server",
                    "scrape_configs": [
                        {
                            "job_name": "loki",
                            "loki_push_api": {
                                "server": {"grpc_listen_port": 3600, "http_listen_port": 3500}
                            },
                        }
                    ],
                },
                {
                    "clients": [
                        {
                            "tls_config": {"insecure_skip_verify": None},
                            "url": "http://loki1:3100/loki/api/v1/push",
                        }
                    ],
                    "name": "log_file_scraper",
                    "scrape_configs": [
                        {
                            "job_name": "varlog",
                            "static_configs": [
                                {
                                    "labels": {
                                        "__path__": "/var/log/*log",
                                        "instance": f"my-model_{my_uuid}_principal_principal/0",
                                        "juju_application": "principal",
                                        "juju_model": "my-model",
                                        "juju_model_uuid": my_uuid,
                                        "juju_unit": "principal/0",
                                    },
                                    "targets": ["localhost"],
                                }
                            ],
                        },
                        {
                            "job_name": "syslog",
                            "journal": {
                                "labels": {
                                    "instance": f"my-model_{my_uuid}_principal_principal/0",
                                    "juju_application": "principal",
                                    "juju_model": "my-model",
                                    "juju_model_uuid": my_uuid,
                                    "juju_unit": "principal/0",
                                }
                            },
                        },
                        {
                            "job_name": "foo",
                            "static_configs": [
                                {
                                    "labels": {
                                        "__path__": "/snap/grafana-agent/current/shared-logs/**/*",
                                        "job": "foo",
                                        "juju_model": "my-model",
                                        "juju_model_uuid": my_uuid,
                                    },
                                    "targets": ["localhost"],
                                }
                            ],
                        },
                        {
                            "job_name": "oh",
                            "static_configs": [
                                {
                                    "labels": {
                                        "__path__": "/snap/grafana-agent/current/shared-logs/**/*",
                                        "job": "oh",
                                        "juju_model": "my-model",
                                        "juju_model_uuid": my_uuid,
                                    },
                                    "targets": ["localhost"],
                                }
                            ],
                        },
                    ],
                },
            ],
            "positions_directory": "${SNAP_DATA}/grafana-agent-positions",
        },
        "metrics": {
            "configs": [{"name": "agent_scraper", "remote_write": [], "scrape_configs": []}],
            "wal_directory": "/tmp/agent/data",
        },
        "server": {"log_level": "info"},
    }
