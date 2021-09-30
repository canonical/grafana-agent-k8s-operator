#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""

import logging

import yaml
from charms.loki_k8s.v0.loki import LokiConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from ops.charm import CharmBase, RelationChangedEvent
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import PathError
from requests import post

logger = logging.getLogger(__name__)

CONFIG_PATH = "/etc/agent/agent.yaml"


class GrafanaAgentOperatorCharm(CharmBase):
    """Grafana Agent Charm."""

    _name = "agent"
    _promtail_positions = "/tmp/positions.yaml"
    _http_listen_port = 3500
    _grpc_listen_port = 3600

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)
        self._remote_write = PrometheusRemoteWriteConsumer(self, "prometheus-remote-write")
        self._scrape = MetricsEndpointConsumer(self)
        self._loki = LokiConsumer(self, "logging")

        self.framework.observe(self.on.agent_pebble_ready, self.on_pebble_ready)
        self.framework.observe(
            self.on["prometheus-remote-write"].relation_changed, self.on_remote_write_changed
        )
        self.framework.observe(self._scrape.on.targets_changed, self.on_scrape_targets_changed)

        self.framework.observe(
            self.on["logging"].relation_changed, self._on_logging_relation_changed
        )

    def _on_logging_relation_changed(self, event):
        logging.warning(event)
        self._update_config()

    def on_pebble_ready(self, event: EventBase) -> None:
        """Event handler for the pebble ready event.

        Args:
            event: The event object of the pebble ready event
        """
        container = event.workload
        container.push(CONFIG_PATH, self._config_file())
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

        self._update_status()

    def on_scrape_targets_changed(self, _) -> None:
        """Event handler for the scrape targets changed event."""
        self._update_config()
        self._update_status()

    def on_remote_write_changed(self, _: RelationChangedEvent) -> None:
        """Event handler for the remote write changed event."""
        self._update_config()
        self._update_status()

    def _update_status(self) -> None:
        """Update the status to reflect the status quo."""
        if len(self.model.relations["metrics-endpoint"]):
            if not len(self.model.relations["prometheus-remote-write"]):
                self.unit.status = BlockedStatus("no related Prometheus remote-write")
                return

        if not self.unit.get_container("agent").can_connect():
            self.unit.status = WaitingStatus("waiting for the agent container to start")
            return

        self.unit.status = ActiveStatus()

    def _update_config(self):

        if not self._container.can_connect():
            # Pebble is not ready yet so no need to update config
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return
        config = self._config_file()
        try:
            old_config = self._container.pull(CONFIG_PATH)
        except PathError:
            # If the file does not yet exist, pebble_ready has not run yet
            pass
        if yaml.safe_load(config) != yaml.safe_load(old_config):
            self._container.push(CONFIG_PATH, config)
            self._reload_config()

    def _cli_args(self) -> str:
        """Return the cli arguments to pass to agent.

        Returns:
            The arguments as a string
        """
        return "-config.file=/etc/agent/agent.yaml -prometheus.wal-directory=/tmp/agent/data"

    def _config_file(self) -> str:
        """Put all the config sections together and return the main config file.

        Returns:
            The config file contents
        """
        config = {}
        if server_config := self._server_config():
            config["server"] = server_config
        if integrations_config := self._integrations_config():
            config["integrations"] = integrations_config
        if prometheus_config := self._prometheus_config():
            config["prometheus"] = prometheus_config
        if loki_config := self._loki_config():
            config["loki"] = loki_config
        return yaml.dump(config)

    def _server_config(self) -> dict:
        """Return the server section of the config.

        Returns:
            The dict representing the config
        """
        return {"log_level": "info"}

    def _integrations_config(self) -> dict:
        """Return the integrations section of the config.

        Returns:
            The dict representing the config
        """
        juju_model = self.model.name
        juju_model_uuid = self.model.uuid
        juju_application = self.model.app.name
        juju_unit = self.unit.name

        instance_value = f"{juju_model}_{juju_model_uuid}_{juju_application}_{juju_unit}"

        return {
            "agent": {
                "enabled": True,
                # Align the "instance" able with the rest of the Juju-collected metrics
                "relabel_configs": [
                    {
                        "target_label": "instance",
                        "regex": "(.*)",
                        "replacement": instance_value,
                    },
                    {  # To add a label, we create a relabelling that replaces a built-in
                        "source_labels": ["__address__"],
                        "target_label": "juju_charm",
                        "replacement": self.meta.name,
                    },
                    {  # To add a label, we create a relabelling that replaces a built-in
                        "source_labels": ["__address__"],
                        "target_label": "juju_model",
                        "replacement": juju_model,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_model_uuid",
                        "replacement": juju_model_uuid,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_application",
                        "replacement": juju_application,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_unit",
                        "replacement": juju_unit,
                    },
                ],
            },
            "prometheus_remote_write": list(self._remote_write.configs),
        }

    def _prometheus_config(self) -> dict:
        """Return the prometheus section of the config.

        Returns:
            The dict representing the config
        """
        return {
            "configs": [
                {
                    "name": "agent_scraper",
                    "scrape_configs": self._scrape.jobs(),
                    "remote_write": list(self._remote_write.configs),
                }
            ]
        }

    def _loki_config(self) -> dict:
        """Return the loki section of the config.

        Returns:
            The dict representing the config
        """
        config = {}

        if loki_push_api := self._loki.loki_push_api:
            config = {
                "configs": [{
                    "name": "promtail_conf",
                    "clients": [{"url": f"{loki_push_api}"}],
                    "positions": {"filename": f"{self._promtail_positions}"},
                    "scrape_configs": [{
                        "job_name": "loki-push",
                        "loki_push_api": {
                            "server": {
                                "http_listen_port": self._http_listen_port,
                                "grpc_listen_port": self._grpc_listen_port,
                            },
                            "labels": {
                                "pushserver": "loki-push"
                            },
                        },
                    }]
                }]
            }

        return config

    def _reload_config(self, attempts: int = 10) -> None:
        """Reload the config file.

        Args:
            attempts: number of attempts to reload
        """
        url = "http://localhost/-/reload"
        for _ in range(attempts):
            response = post(url)
            if response.status_code == 200:
                break
        else:
            raise Exception("Error: Could not reload config.")


if __name__ == "__main__":
    main(GrafanaAgentOperatorCharm)
