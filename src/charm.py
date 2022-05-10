#!/usr/bin/env python3

# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""

import logging
import os
import pathlib
import shutil
from typing import Any, Dict

import yaml
from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer, LokiPushApiProvider
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from ops.charm import CharmBase, RelationChangedEvent
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import APIError, PathError
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

CONFIG_PATH = "/etc/agent/agent.yaml"
METRICS_RULES_SRC_PATH = "./src/prometheus_alert_rules"
METRICS_RULES_DEST_PATH = "./prometheus_alert_rules"
REMOTE_WRITE_RELATION_NAME = "send-remote-write"
SCRAPE_RELATION_NAME = "metrics-endpoint"


class GrafanaAgentReloadError(Exception):
    """Custom exception to indicate that grafana agent config couldn't be reloaded."""

    def __init__(self, message="could not reload configuration"):
        self.message = message
        super().__init__(self.message)


class GrafanaAgentOperatorCharm(CharmBase):
    """Grafana Agent Charm."""

    _name = "agent"
    _promtail_positions = "/tmp/positions.yaml"
    _http_listen_port = 3500
    _grpc_listen_port = 3600

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)
        self._metrics_rules_src_path = os.path.join(self.charm_dir, METRICS_RULES_SRC_PATH)
        self._metrics_rules_dest_path = os.path.join(self.charm_dir, METRICS_RULES_DEST_PATH)
        self.service_patch = KubernetesServicePatch(
            self,
            [
                (f"{self.app.name}-http-listen-port", self._http_listen_port),
                (f"{self.app.name}-grpc-listen-port", self._grpc_listen_port),
            ],
        )

        if not os.path.isdir(self._metrics_rules_dest_path):
            shutil.copytree(
                self._metrics_rules_src_path, self._metrics_rules_dest_path, dirs_exist_ok=True
            )
        self._remote_write = PrometheusRemoteWriteConsumer(
            self, alert_rules_path=self._metrics_rules_dest_path
        )
        self._scrape = MetricsEndpointConsumer(self)

        self._loki_consumer = LokiPushApiConsumer(self, relation_name="logging-consumer")
        self._loki_provider = LokiPushApiProvider(
            self, relation_name="logging-provider", port=self._http_listen_port
        )

        self.framework.observe(self.on.agent_pebble_ready, self.on_pebble_ready)
        self.framework.observe(self.on.upgrade_charm, self.update_alerts_rules)

        self.framework.observe(
            self._remote_write.on.endpoints_changed, self.on_remote_write_changed
        )
        self.framework.observe(self._remote_write.on.endpoints_changed, self.update_alerts_rules)

        self.framework.observe(self._scrape.on.targets_changed, self.on_scrape_targets_changed)
        self.framework.observe(self._scrape.on.targets_changed, self.update_alerts_rules)

        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_joined,
            self._on_loki_push_api_endpoint_joined,
        )
        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_departed,
            self._on_loki_push_api_endpoint_departed,
        )

    def update_alerts_rules(self, _):
        """Copy alert rules from relations and save them to disk."""
        rules = self._scrape.alerts()
        shutil.rmtree(self._metrics_rules_dest_path)
        shutil.copytree(self._metrics_rules_src_path, self._metrics_rules_dest_path)
        for topology_identifier, rule in rules.items():
            file_handle = pathlib.Path(
                self._metrics_rules_dest_path, "juju_{}.rules".format(topology_identifier)
            )
            file_handle.write_text(yaml.dump(rule))
            logger.debug("updated alert rules file {}".format(file_handle.absolute()))
        self._remote_write.reload_alerts()

    def _on_loki_push_api_endpoint_joined(self, event) -> None:
        """Event handler for the logging relation changed event."""
        self._update_config(event)

    def _on_loki_push_api_endpoint_departed(self, event) -> None:
        """Event handler for the loki departed."""
        self._update_config(event)

    def on_pebble_ready(self, _: EventBase) -> None:
        """Event handler for the pebble ready event.

        Args:
            event: The event object of the pebble ready event
        """
        self._container.push(CONFIG_PATH, yaml.dump(self._config_file()), make_dirs=True)

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

    def on_scrape_targets_changed(self, event) -> None:
        """Event handler for the scrape targets changed event."""
        self._update_config(event)
        self._update_status()

    def on_remote_write_changed(self, event: RelationChangedEvent) -> None:
        """Event handler for the remote write changed event."""
        self._update_config(event)
        self._update_status()

    def _update_status(self) -> None:
        """Update the status to reflect the status quo."""
        if len(self.model.relations["metrics-endpoint"]):
            if not len(self.model.relations[REMOTE_WRITE_RELATION_NAME]):
                self.unit.status = BlockedStatus("no related Prometheus remote-write")
                return

        if not self.unit.get_container("agent").can_connect():
            self.unit.status = WaitingStatus("waiting for the agent container to start")
            return

        self.unit.status = ActiveStatus()

    def _update_config(self, event=None):
        if not self._container.can_connect():
            # Pebble is not ready yet so no need to update config
            self.unit.status = WaitingStatus("waiting for agent container to start")
            return

        config = self._config_file()
        old_config = None

        try:
            old_config = yaml.safe_load(self._container.pull(CONFIG_PATH))
        except (FileNotFoundError, PathError):
            # If the file does not yet exist, pebble_ready has not run yet,
            # and we may be processing a deferred event
            pass

        try:
            if config != old_config:
                self._container.push(CONFIG_PATH, yaml.dump(config), make_dirs=True)
                # FIXME: change this to self._reload_config when #19 is fixed
                # Restart the service to pick up the new config
                self._container.restart(self._name)
                self.unit.status = ActiveStatus()
        except GrafanaAgentReloadError as e:
            self.unit.status = BlockedStatus(str(e))
        except APIError as e:
            self.unit.status = WaitingStatus(str(e))

    def _cli_args(self) -> str:
        """Return the cli arguments to pass to agent.

        Returns:
            The arguments as a string
        """
        return "-config.file=/etc/agent/agent.yaml -prometheus.wal-directory=/tmp/agent/data"

    def _config_file(self) -> Dict[str, Any]:
        """Generates config file str.

        Returns:
            A yaml string with grafana agent config
        """
        config = {}
        config.update(self._server_config())
        config.update(self._integrations_config())
        config.update(self._prometheus_config())
        config.update(self._loki_config())
        return config

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

        job_name = f"juju_{juju_model}_{juju_model_uuid}_{juju_application}_self-monitoring"
        instance_value = f"{juju_model}_{juju_model_uuid}_{juju_application}_{juju_unit}"

        return {
            "integrations": {
                "agent": {
                    "enabled": True,
                    "relabel_configs": [
                        # Align the "job" name with those of prometheus_scrape
                        {
                            "target_label": "job",
                            "regex": "(.*)",
                            "replacement": job_name,
                        },
                        # Align the "instance" label with the rest of the Juju-collected metrics
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
                "prometheus_remote_write": self._remote_write.endpoints,
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
                        "remote_write": self._remote_write.endpoints,
                    }
                ]
            }
        }

    def _loki_config(self) -> dict:
        """Modifies the loki section of the config.

        Returns:
            a dict with Loki config
        """
        if not self._loki_consumer.loki_endpoints:
            return {"loki": {}}

        return {
            "loki": {
                "configs": [
                    {
                        "name": "promtail",
                        "clients": self._loki_consumer.loki_endpoints,
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
