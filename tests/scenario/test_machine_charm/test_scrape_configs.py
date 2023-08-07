#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import inspect
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import machine_charm
import pytest
import yaml
from charms.grafana_agent.v0.cos_agent import CosAgentProviderUnitData
from scenario import Context, Model, PeerRelation, Relation, State, SubordinateRelation

machine_meta = yaml.safe_load(
    (
        Path(inspect.getfile(machine_charm.GrafanaAgentMachineCharm)).parent.parent
        / "machine_metadata.yaml"
    ).read_text()
)


@pytest.fixture(autouse=True)
def patch_all(placeholder_cfg_path):
    with patch("grafana_agent.CONFIG_PATH", placeholder_cfg_path):
        yield


def test_snap_endpoints(placeholder_cfg_path):
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
        "cos-agent", remote_app_name="principal", remote_unit_data={data.KEY: data.json()}
    )

    vroot = tempfile.TemporaryDirectory()
    vroot_path = Path(vroot.name)
    vroot_path.joinpath("src", "loki_alert_rules").mkdir(parents=True)
    vroot_path.joinpath("src", "prometheus_alert_rules").mkdir(parents=True)
    vroot_path.joinpath("src", "grafana_dashboards").mkdir(parents=True)

    my_uuid = str(uuid.uuid4())

    with patch("charms.operator_libs_linux.v1.snap.SnapCache"), patch(
        "machine_charm.GrafanaAgentMachineCharm.write_file", new=mock_write
    ), patch("machine_charm.GrafanaAgentMachineCharm.is_ready", return_value=True):
        state = State(
            relations=[cos_relation, loki_relation, PeerRelation("peers")],
            model=Model(name="my-model", uuid=my_uuid),
        )

        ctx = Context(
            charm_type=machine_charm.GrafanaAgentMachineCharm,
            meta=machine_meta,
            charm_root=vroot.name,
        )
        ctx.run(state=state, event=cos_relation.changed_event)

    assert written_path == placeholder_cfg_path
    written_config = yaml.safe_load(written_text)
    logs_configs = written_config["logs"]["configs"]
    for config in logs_configs:
        if config["name"] == "log_file_scraper":
            scrape_job_names = [job["job_name"] for job in config["scrape_configs"]]
            assert "foo" in scrape_job_names
            assert "oh" in scrape_job_names
            assert "shameless_plug" not in scrape_job_names
