# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Common logic for both k8s and machine charms for Grafana Agent."""
import logging
import os
import pathlib
import re
import shutil
from collections import namedtuple
from typing import Any, Callable, Dict, Optional, Union

import yaml
from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer, LokiPushApiProvider
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from ops.charm import CharmBase, RelationChangedEvent
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import APIError, PathError
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

CONFIG_PATH = "/etc/grafana-agent.yaml"
LOKI_RULES_SRC_PATH = "./src/loki_alert_rules"
LOKI_RULES_DEST_PATH = "./loki_alert_rules"
METRICS_RULES_SRC_PATH = "./src/prometheus_alert_rules"
METRICS_RULES_DEST_PATH = "./prometheus_alert_rules"
REMOTE_WRITE_RELATION_NAME = "send-remote-write"
SCRAPE_RELATION_NAME = "metrics-endpoint"

RulesMapping = namedtuple("RulesMapping", ["src", "dest"])


class GrafanaAgentReloadError(Exception):
    """Custom exception to indicate that grafana agent config couldn't be reloaded."""

    def __init__(self, message="could not reload configuration"):
        self.message = message
        super().__init__(self.message)


class GrafanaAgentCharm(CharmBase):
    """Grafana Agent Charm."""

    _name = "agent"
    _promtail_positions = "/tmp/positions.yaml"
    _http_listen_port = 3500
    _grpc_listen_port = 3600

    def __init__(self, *args):
        super().__init__(*args)

        self.loki_rules_paths = RulesMapping(
            src=os.path.join(self.charm_dir, LOKI_RULES_SRC_PATH),
            dest=os.path.join(self.charm_dir, LOKI_RULES_DEST_PATH),
        )
        self.metrics_rules_paths = RulesMapping(
            src=os.path.join(self.charm_dir, METRICS_RULES_SRC_PATH),
            dest=os.path.join(self.charm_dir, METRICS_RULES_DEST_PATH),
        )

        for rules in [self.loki_rules_paths, self.metrics_rules_paths]:
            if not os.path.isdir(rules.dest):
                shutil.copytree(rules.src, rules.dest, dirs_exist_ok=True)

        self._remote_write = PrometheusRemoteWriteConsumer(
            self, alert_rules_path=self.metrics_rules_paths.dest
        )
        self._scrape = MetricsEndpointConsumer(self)

        self._loki_consumer = LokiPushApiConsumer(
            self, relation_name="logging-consumer", alert_rules_path=self.loki_rules_paths.dest
        )
        self._loki_provider = LokiPushApiProvider(
            self, relation_name="logging-provider", port=self._http_listen_port
        )

        self.framework.observe(self.on.upgrade_charm, self._metrics_alerts)
        self.framework.observe(self.on.upgrade_charm, self._loki_alerts)

        self.framework.observe(
            self._remote_write.on.endpoints_changed, self.on_remote_write_changed
        )
        self.framework.observe(self._remote_write.on.endpoints_changed, self._metrics_alerts)

        self.framework.observe(self._scrape.on.targets_changed, self.on_scrape_targets_changed)
        self.framework.observe(self._scrape.on.targets_changed, self._metrics_alerts)

        self.framework.observe(
            self._loki_provider.on.loki_push_api_alert_rules_changed, self._loki_alerts
        )

        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_joined,
            self._on_loki_push_api_endpoint_joined,
        )
        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_departed,
            self._on_loki_push_api_endpoint_departed,
        )
        self.framework.observe(self.on.config_changed, self._update_config)

    # Abstract Methods

    def agent_version_output(self) -> str:
        """Gets the raw output from `agent -version`."""
        raise NotImplementedError("Please override the agent_version_output method")

    def is_ready(self):
        """Checks if the charm is ready for configuration."""
        raise NotImplementedError("Please override the is_ready method")

    def read_file(self, filepath: Union[str, pathlib.Path]):
        """Read a file's contents.

        Returns:
            A string with the file's contents
        """
        raise NotImplementedError("Please override the read_file method")

    def write_file(self, path: Union[str, pathlib.Path], text: str) -> None:
        """Write text to a file.

        Args:
            path: file path to write to
            text: text to write to the file
        """
        raise NotImplementedError("Please override the write_file method")

    def restart(self) -> None:
        """Restart grafana agent."""
        raise NotImplementedError("Please override the restart method")

    def is_machine(self) -> bool:
        """Check if this is a machine charm."""
        raise NotImplementedError("Please override the is_machine method")

    # End: Abstract Methods

    def _metrics_alerts(self, event):
        self.update_alerts_rules(
            event,
            alerts_func=self._scrape.alerts,
            reload_func=self._remote_write.reload_alerts,
            mapping=self.metrics_rules_paths,
        )

    def _loki_alerts(self, event):
        self.update_alerts_rules(
            event,
            alerts_func=self._loki_provider.alerts,
            reload_func=self._loki_consumer._reinitialize_alert_rules,
            mapping=self.loki_rules_paths,
        )

    def update_alerts_rules(
        self, _, alerts_func: Any, reload_func: Callable, mapping: RulesMapping
    ):
        """Copy alert rules from relations and save them to disk."""
        rules = {}

        # MetricsEndpointConsumer.alerts is not @property, but Loki is, so
        # do the right thing
        if callable(alerts_func):
            rules = alerts_func()
        else:
            rules = alerts_func

        shutil.rmtree(mapping.dest)
        shutil.copytree(mapping.src, mapping.dest)
        for topology_identifier, rule in rules.items():
            file_handle = pathlib.Path(mapping.dest, "juju_{}.rules".format(topology_identifier))
            file_handle.write_text(yaml.dump(rule))
            logger.debug("updated alert rules file {}".format(file_handle.absolute()))
        reload_func()

    def _on_loki_push_api_endpoint_joined(self, event) -> None:
        """Event handler for the logging relation changed event."""
        self._update_config(event)

    def _on_loki_push_api_endpoint_departed(self, event) -> None:
        """Event handler for the loki departed."""
        self._update_config(event)

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
                self.unit.status = WaitingStatus("no related Prometheus remote-write")
                return

        if not self.is_ready():
            self.unit.status = WaitingStatus("waiting for the agent to start")
            return

        self.unit.status = ActiveStatus()

    def _update_config(self, event) -> None:
        if not self.is_ready():
            # Grafana-agent is not yet available so no need to update config
            self.unit.status = WaitingStatus("waiting for agent to start")
            return

        config = self._config_file()
        old_config = None

        try:
            old_config = yaml.safe_load(self.read_file(CONFIG_PATH))
        except (FileNotFoundError, PathError):
            # If the file does not yet exist, pebble_ready has not run yet,
            # and we may be processing a deferred event
            pass

        try:
            if config != old_config:
                self.write_file(CONFIG_PATH, yaml.dump(config))
                # FIXME: change this to self._reload_config when #19 is fixed
                # Restart the service to pick up the new config
                self.restart()
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
        return f"-config.file={CONFIG_PATH}"

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

        # Align the "job" name with those of prometheus_scrape
        job_name = f"juju_{juju_model}_{juju_model_uuid}_{juju_application}_self-monitoring"
        instance_value = f"{juju_model}_{juju_model_uuid}_{juju_application}_{juju_unit}"

        relabel_configs = [
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
        ]

        conf = {
            "integrations": {
                "agent": {
                    "enabled": True,
                    "relabel_configs": [
                        {
                            "target_label": "job",
                            "regex": "(.*)",
                            "replacement": job_name,
                        },
                    ]
                    + relabel_configs,
                },
                "prometheus_remote_write": self._remote_write.endpoints,
            }
        }

        if self.is_machine():
            node_exporter_job_name = (
                f"juju_{juju_model}_{juju_model_uuid}_{juju_application}_node-exporter"
            )
            conf["integrations"]["node_exporter"] = {
                "enabled": True,
                "relabel_configs": [
                    # Align the "job" name with those of prometheus_scrape
                    {
                        "target_label": "job",
                        "regex": "(.*)",
                        "replacement": node_exporter_job_name,
                    },
                ]
                + self.get_principal_relabels(),
            }

        return conf

    def _prometheus_config(self) -> dict:
        """Return the prometheus section of the config.

        Returns:
            The dict representing the config
        """
        return {
            "metrics": {
                "wal_directory": "/tmp/agent/data",
                "configs": [
                    {
                        "name": "agent_scraper",
                        "scrape_configs": self._scrape.jobs(),
                        "remote_write": self._remote_write.endpoints,
                    }
                ],
            }
        }

    def _loki_config(self) -> dict:
        """Modifies the loki section of the config.

        Returns:
            a dict with Loki config
        """
        logs_config = {
            "logs": {
                "configs": [],
            }
        }

        if self._loki_consumer.loki_endpoints:
            logs_config["logs"]["configs"].append(
                {
                    "name": "push_api_server",
                    "clients": self._loki_consumer.loki_endpoints,
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
            )

        if self.is_machine():
            logs_config["logs"]["configs"].append(
                {
                    "name": "log_file_scraper",
                    "clients": self._loki_consumer.loki_endpoints,
                    "scrape_configs": [
                        {
                            "job_name": "varlog",
                            "static_configs": {
                                "labels": {
                                    "__path__": "/var/log/*",
                                    "__path_exclude__": "/var/log/positions.yaml",
                                    **self.get_principal_labels(),
                                }
                            },
                        },
                        {"job_name": "syslog", "journal": {"labels": self.get_principal_labels()}},
                    ],
                }
            )
            
        return logs_config

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

    @property
    def _agent_version(self) -> Optional[str]:
        """Returns the version of the agent.

        Returns:
            A string equal to the agent version
        """
        if not self.is_ready():
            return None
        version_output = self.agent_version_output()
        # Output looks like this:
        # agent, version v0.26.1 (branch: HEAD, revision: 2b88be37)
        result = re.search(r"v(\d*\.\d*\.\d*)", version_output)
        if result is None:
            return result
        return result.group(1)
