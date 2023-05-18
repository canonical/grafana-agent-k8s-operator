#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""
import logging
import pathlib
from typing import Any, Dict, List, Union

import yaml
from charms.loki_k8s.v0.loki_push_api import LokiPushApiProvider
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
    ServicePort,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from grafana_agent import CONFIG_PATH, GrafanaAgentCharm
from ops.main import main

logger = logging.getLogger(__name__)

SCRAPE_RELATION_NAME = "metrics-endpoint"


class GrafanaAgentK8sCharm(GrafanaAgentCharm):
    """K8s version of the Grafana Agent charm."""

    mandatory_relation_pairs = [
        ("metrics-endpoint", ["send-remote-write", "grafana-cloud-config"]),
        ("grafana-dashboards-consumer", ["grafana-dashboards-provider", "grafana-cloud-config"]),
        ("logging-provider", ["logging-consumer", "grafana-cloud-config"]),
    ]

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)

        self.service_patch = KubernetesServicePatch(
            self,
            [
                ServicePort(self._http_listen_port, name=f"{self.app.name}-http-listen-port"),
                ServicePort(self._grpc_listen_port, name=f"{self.app.name}-grpc-listen-port"),
            ],
        )
        self._scrape = MetricsEndpointConsumer(self)
        self.framework.observe(
            self._scrape.on.targets_changed,  # pyright: ignore
            self.on_scrape_targets_changed,
        )

        self._loki_provider = LokiPushApiProvider(
            self, relation_name="logging-provider", port=self._http_listen_port
        )
        self.framework.observe(
            self._loki_provider.on.loki_push_api_alert_rules_changed,  # pyright: ignore
            self._on_loki_push_api_alert_rules_changed,
        )

        self.framework.observe(
            self.on.agent_pebble_ready,  # pyright: ignore
            self._on_agent_pebble_ready,
        )

    def _on_loki_push_api_alert_rules_changed(self, _event):
        """Refresh Loki alert rules."""
        self._update_loki_alerts()

    def _on_agent_pebble_ready(self, _event) -> None:
        self._container.push(CONFIG_PATH, yaml.dump(self._generate_config()), make_dirs=True)

        pebble_layer = {
            "summary": "agent layer",
            "description": "pebble config layer for Grafana Agent",
            "services": {
                "agent": {
                    "override": "replace",
                    "summary": "agent",
                    "command": f"/bin/agent {self._cli_args()}",
                    "startup": "enabled",
                },
            },
        }
        self._container.add_layer(self._name, pebble_layer, combine=True)
        self._container.autostart()

        if (version := self._agent_version) is not None:
            self.unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: could not get grafana-agent version."
            )
        self._update_status()

    def metrics_rules(self) -> Dict[str, Any]:
        """Return a list of metrics rules."""
        return self._scrape.alerts

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        return self._scrape.jobs()

    def logs_rules(self) -> Dict[str, Any]:
        """Return a list of logging rules."""
        return self._loki_provider.alerts

    @property
    def is_ready(self):
        """Checks if the charm is ready for configuration."""
        return self._container.can_connect()

    @property
    def _additional_integrations(self) -> Dict:
        """No additions for k8s charms."""
        return {}

    @property
    def _additional_log_configs(self) -> List[Dict[str, Any]]:
        """Additional per-type integrations to inject."""
        return []

    def agent_version_output(self) -> str:
        """Runs `agent -version` and returns the output.

        Returns:
            Output of `agent -version`
        """
        version_output, _ = self._container.exec(["/bin/agent", "-version"]).wait_output()
        return version_output

    def read_file(self, filepath: Union[str, pathlib.Path]):
        """Read a file's contents.

        Returns:
            A string with the file's contents
        """
        return self._container.pull(filepath).read()

    def write_file(self, path: Union[str, pathlib.Path], text: str) -> None:
        """Write text to a file.

        Args:
            path: file path to write to
            text: text to write to the file
        """
        self._container.push(path, text, make_dirs=True)

    def restart(self) -> None:
        """Restart grafana agent."""
        self._container.restart("agent")

    def positions_dir(self) -> str:
        """Return the positions directory."""
        return "/run"


if __name__ == "__main__":
    main(GrafanaAgentK8sCharm)
