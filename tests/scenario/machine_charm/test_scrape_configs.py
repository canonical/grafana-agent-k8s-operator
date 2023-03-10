import inspect
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
from scenario import State, Relation

import machine_charm

machine_meta = yaml.safe_load(
    (Path(inspect.getfile(machine_charm.GrafanaAgentMachineCharm)).parent.parent / 'machine_metadata.yaml').read_text()
)


def test_snap_endpoints():
    written_path, written_text = "", ""

    def mock_write(path, text):
        nonlocal written_path, written_text
        written_path = path
        written_text = text

    cos_relation = Relation(
        'cos-machine',
        remote_app_name='principal',
        remote_app_data={
            'config': json.dumps({
                "metrics": {
                    "scrape_jobs": [],
                    "alert_rules": [],
                },
                "logs": {
                    "targets": ['foo:bar', 'oh:snap', 'shameless-plug'],
                    "alert_rules": [],
                },
                "dashboards": {
                    "dashboards": [],
                },
            }
            )
        })

    vroot = tempfile.TemporaryDirectory()
    vroot_path = Path(vroot.name)
    vroot_path.joinpath('src', 'loki_alert_rules').mkdir(parents=True)
    vroot_path.joinpath('src', 'prometheus_alert_rules').mkdir(parents=True)
    vroot_path.joinpath('src', 'grafana_dashboards').mkdir(parents=True)

    with patch('machine_charm.GrafanaAgentMachineCharm.write_file', new=mock_write):
        with patch('machine_charm.GrafanaAgentMachineCharm.is_ready', return_value=True):
            State(
                relations=[cos_relation]
            ).trigger(
                event=cos_relation.changed_event,
                charm_type=machine_charm.GrafanaAgentMachineCharm,
                meta=machine_meta,
                charm_root=vroot.name
            )

    assert written_path
    assert written_text
