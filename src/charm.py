#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""

import logging

import yaml
from charms.loki_k8s.v0.loki_push_api import (
    LogProxyProvider,
    LokiPushApiConsumer,
    LokiPushApiEndpointDeparted,
    LokiPushApiEndpointJoined,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from ops.charm import CharmBase, RelationChangedEvent
from ops.framework import EventBase, StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import PathError
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from kubernetes_service import K8sServicePatch, PatchFailed

logger = logging.getLogger(__name__)

CONFIG_PATH = "/etc/agent/agent.yaml"


class GrafanaAgentReloadError(Exception):
    """Custom exception to indicate that grafana agent config couldn't be reloaded."""

    def __init__(self, message="could not reload configuration"):
        self.message = message
        super().__init__(self.message)


class GrafanaAgentOperatorCharm(CharmBase):
    """Grafana Agent Charm."""

    _stored = StoredState()
    _name = "agent"
    _promtail_positions = "/tmp/positions.yaml"
    _http_listen_port = 3500
    _grpc_listen_port = 3600

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)
        self._stored.set_default(k8s_service_patched=False, config="")
        self._remote_write = PrometheusRemoteWriteConsumer(self)
        self._scrape = MetricsEndpointConsumer(self)

        self._loki_consumer = LokiPushApiConsumer(self)
        self._log_proxy = LogProxyProvider(self)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.agent_pebble_ready, self.on_pebble_ready)
        self.framework.observe(
            self.on["prometheus-remote-write"].relation_changed, self.on_remote_write_changed
        )
        self.framework.observe(self._scrape.on.targets_changed, self.on_scrape_targets_changed)
        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_joined,
            self._on_loki_push_api_endpoint_joined,
        )
        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_departed,
            self._on_loki_push_api_endpoint_departed,
        )

    def _on_install(self, _):
        """Handler for the install event during which we will update the K8s service."""
        self._patch_k8s_service()

    def _on_loki_push_api_endpoint_joined(self, event) -> None:
        """Event handler for the logging relation changed event."""
        self._update_config(event)

    def _on_loki_push_api_endpoint_departed(self, event) -> None:
        """Event handler for the loki departed."""
        self._update_config(event)

    def on_pebble_ready(self, event: EventBase) -> None:
        """Event handler for the pebble ready event.

        Args:
            event: The event object of the pebble ready event
        """
        container = event.workload
        config = self._config_file(event)
        container.push(CONFIG_PATH, config)
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

    def _patch_k8s_service(self):
        """Fix the Kubernetes service that was setup by Juju with correct port numbers."""
        if self.unit.is_leader() and not self._stored.k8s_service_patched:
            service_ports = [
                (
                    f"{self.app.name}-http-listen-port",
                    self._http_listen_port,
                    self._http_listen_port,
                ),
                (
                    f"{self.app.name}-grpc-listen-port",
                    self._grpc_listen_port,
                    self._grpc_listen_port,
                ),
            ]
            try:
                K8sServicePatch.set_ports(self.app.name, service_ports)
            except PatchFailed as e:
                logger.error("Unable to patch the Kubernetes service: %s", str(e))
            else:
                self._stored.k8s_service_patched = True
                logger.info("Successfully patched the Kubernetes service!")

    def _update_config(self, event=None):

        if not self._container.can_connect():
            # Pebble is not ready yet so no need to update config
            self.unit.status = WaitingStatus("waiting for agent container to start")
            return

        config = self._config_file(event)

        try:
            old_config = self._container.pull(CONFIG_PATH)
        except PathError:
            # If the file does not yet exist, pebble_ready has not run yet
            pass

        try:
            if yaml.safe_load(config) != yaml.safe_load(old_config):
                self._container.push(CONFIG_PATH, config)
                self._reload_config()
                self.unit.status = ActiveStatus()
        except GrafanaAgentReloadError as e:
            self.unit.status = BlockedStatus(str(e))

    def _cli_args(self) -> str:
        """Return the cli arguments to pass to agent.

        Returns:
            The arguments as a string
        """
        return "-config.file=/etc/agent/agent.yaml -prometheus.wal-directory=/tmp/agent/data"

    def _config_file(self, event: EventBase) -> str:
        """Generates config file str based on the event received.

        Returns:
            A yaml string with grafana agent config
        """
        config = {}
        config.update(self._server_config())
        config.update(self._integrations_config())
        config.update(self._prometheus_config())
        config.update(self._loki_config(event))

        return yaml.dump(config)

    def _server_config(self) -> dict:
        """Return the server section of the config.

        Returns:
            The dict representing the config
        """
        return {"server": {"log_level": "info"}}

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
            "integrations": {
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
        }

    def _prometheus_config(self) -> dict:
        """Return the prometheus section of the config.

        Returns:
            The dict representing the config
        """
        return {
            "prometheus": {
                "configs": [
                    {
                        "name": "agent_scraper",
                        "scrape_configs": self._scrape.jobs(),
                        "remote_write": list(self._remote_write.configs),
                    }
                ]
            }
        }

    def _loki_config(self, event: EventBase) -> dict:
        """Modifies the loki section of the config.

        Returns:
            a dict with Loki config
        """
        if isinstance(event, LokiPushApiEndpointDeparted):
            return {"loki": {}}

        if isinstance(event, LokiPushApiEndpointJoined):
            return {
                "loki": {
                    "configs": [
                        {
                            "name": "promtail",
                            "clients": [{"url": f"{self._loki_consumer.loki_push_api}"}],
                            "positions": {"filename": f"{self._promtail_positions}"},
                            "scrape_configs": [
                                {
                                    "job_name": "loki",
                                    "loki_push_api": {
                                        "server": {
                                            "http_listen_port": self._http_listen_port,
                                            "grpc_listen_port": self._grpc_listen_port,
                                        },
                                    },
                                }
                            ],
                        }
                    ]
                }
            }

        return {"loki": {}}

    def _reload_config(self, attempts: int = 10) -> None:
        """Reload the config file.

        Args:
            attempts: number of attempts to reload

        Raises:
            GrafanaAgentReloadError: if configuration could not be reloaded.
        """
        try:
            self.unit.status = MaintenanceStatus("reloading agent configuration")
            url = "http://localhost/-/reload"
            errors = list(range(400, 452)) + list(range(500, 513))
            s = Session()
            retries = Retry(total=attempts, backoff_factor=0.1, status_forcelist=errors)
            s.mount("http://", HTTPAdapter(max_retries=retries))
            s.post(url)
        except Exception as e:
            message = f"could not reload configuration: {str(e)}"
            raise GrafanaAgentReloadError(message)


if __name__ == "__main__":
    main(GrafanaAgentOperatorCharm)
