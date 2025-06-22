import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from ops.testing import Context

from charm import GrafanaAgentK8sCharm


@pytest.fixture
def ctx():
    yield Context(GrafanaAgentK8sCharm)


@pytest.fixture(autouse=True)
def patch_charm_paths():
    base = Path(tempfile.mkdtemp())

    # Create src/prometheus_alert_rules inside base dir
    rules_src = base / "src" / "prometheus_alert_rules"
    rules_src.mkdir(parents=True)

    (rules_src / "sample.rule").write_text("groups: []")

    rules_dest = tempfile.mkdtemp()

    with (
        patch("grafana_agent.GrafanaAgentCharm.charm_dir", base),
        patch("grafana_agent.METRICS_RULES_SRC_PATH", "src/prometheus_alert_rules"),
        patch("grafana_agent.METRICS_RULES_DEST_PATH", rules_dest),
    ):
        yield

@pytest.fixture(autouse=True)
def patch_buffer_file_for_charm_tracing(tmp_path):
    with patch(
        "charms.tempo_coordinator_k8s.v0.charm_tracing.BUFFER_DEFAULT_CACHE_FILE_NAME",
        str(tmp_path / "foo.json"),
    ):
        yield


@pytest.fixture(autouse=True)
def silence_tracing():
    with charm_tracing_disabled():
        yield
