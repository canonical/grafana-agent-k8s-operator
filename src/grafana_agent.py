# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Common logic for both k8s and machine charms for Grafana Agent."""
import logging
import os
import pathlib
import re
import shutil
from collections import namedtuple
from typing import Any, Callable, Dict, List, Optional, Union

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
    _promtail_positions = "/run/promtail-positions.yaml"
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

        self._loki_consumer = LokiPushApiConsumer(
            self, relation_name="logging-consumer", alert_rules_path=self.loki_rules_paths.dest
        )

        self.framework.observe(self.on.upgrade_charm, self._update_metrics_alerts)
        self.framework.observe(self.on.upgrade_charm, self._update_loki_alerts)

        self.framework.observe(
            self._remote_write.on.endpoints_changed, self.on_remote_write_changed
        )
        self.framework.observe(self._remote_write.on.endpoints_changed, self._update_metrics_alerts)

        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_joined, self._update_config
        )
        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_departed, self._update_config
        )
        self.framework.observe(self.on.config_changed, self._update_config)

    # Abstract Methods

    def agent_version_output(self) -> str:
        """Gets the raw output from `agent -version`."""
        raise NotImplementedError("Please override the agent_version_output method")

    @property
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

    @property
    def _additional_integrations(self) -> Dict[str, Any]:
        """Additional per-type integrations to inject."""
        raise NotImplementedError("Please override the _additional_integrations method")

    @property
    def _additional_log_configs(self) -> List[Dict[str, Any]]:
        """Additional per-type integrations to inject."""
        raise NotImplementedError("Please override the _additional_log_configs method")

    def metrics_rules(self) -> list:
        """Return a list of metrics rules."""
        raise NotImplementedError("Please override the metrics_rules method")

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        raise NotImplementedError("Please override the metrics_jobs method")

    def logs_rules(self) -> list:
        """Return a list of logging rules."""
        raise NotImplementedError("Please override the logs_rules method")

    # End: Abstract Methods

    def _update_metrics_alerts(self, event):
        self.update_alerts_rules(
            event,
            alerts_func=self.metrics_rules,
            reload_func=self._remote_write.reload_alerts,
            mapping=self.metrics_rules_paths,
        )

    def _update_loki_alerts(self, event):
        self.update_alerts_rules(
            event,
            alerts_func=self.logs_rules,
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

    def on_scrape_targets_changed(self, event) -> None:
        """Event handler for the scrape targets changed event."""
        self._update_config(event)
        self._update_status()

    def on_remote_write_changed(self, event: RelationChangedEvent) -> None:
        """Event handler for the remote write changed event."""
        self._update_config(event)
        self._update_status()

    def _update_status(self) -> bool:
        """Update the status to reflect the status quo.

        Returns:
            True if the status was set to Active; False otherwise.
        """
        if len(self.model.relations["metrics-endpoint"]):
            if not len(self.model.relations[REMOTE_WRITE_RELATION_NAME]):
                self.unit.status = WaitingStatus("no related Prometheus remote-write")
                return False

        if not self.is_ready:
            self.unit.status = WaitingStatus("waiting for the agent to start")
            return False

        self.unit.status = ActiveStatus()
        return True

    def _update_config(self, _) -> None:
        if not self.is_ready:
            # Grafana-agent is not yet available so no need to update config
            self.unit.status = WaitingStatus("waiting for agent to start")
            return

        config = self._generate_config()
        old_config = None

        try:
            old_config = yaml.safe_load(self.read_file(CONFIG_PATH))
        except (FileNotFoundError, PathError):
            # If the file does not yet exist, pebble_ready has not run yet,
            # and we may be processing a deferred event
            pass

        if config == old_config:
            # Nothing changed, possibly new install. Set us active and move on.
            self.unit.status = ActiveStatus()
            return

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

    def _generate_config(self) -> Dict[str, Any]:
        """Generates config file str.

        Returns:
            A yaml string with grafana agent config
        """
        config = {
            "server": {"log_level": "info"},
            "integrations": self._integrations_config,
            "metrics": {
                "wal_directory": "/tmp/agent/data",
                "configs": [
                    {
                        "name": "agent_scraper",
                        "scrape_configs": self.metrics_jobs,
                        "remote_write": self._remote_write.endpoints,
                    }
                ],
            },
            "logs": self._loki_config,
        }
        return config

    @property
    def _integrations_config(self) -> dict:
        """Return the integrations section of the config.

        Returns:
            The dict representing the config
        """
        juju_model = self.model.name
        juju_model_uuid = self.model.uuid
        juju_application = self.model.app.name

        # Align the "job" name with those of prometheus_scrape
        job_name = f"juju_{juju_model}_{juju_model_uuid}_{juju_application}_self-monitoring"

        conf = {
            "agent": {
                "enabled": True,
                "relabel_configs": [
                    {
                        "target_label": "job",
                        "regex": "(.*)",
                        "replacement": job_name,
                    },
                    {  # Align the "instance" label with the rest of the Juju-collected metrics
                        "target_label": "instance",
                        "regex": "(.*)",
                        "replacement": self._instance_name,
                    },
                    {  # To add a label, we create a relabelling that replaces a built-in
                        "source_labels": ["__address__"],
                        "target_label": "juju_charm",
                        "replacement": self.meta.name,
                    },
                    {  # To add a label, we create a relabelling that replaces a built-in
                        "source_labels": ["__address__"],
                        "target_label": "juju_model",
                        "replacement": self.model.name,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_model_uuid",
                        "replacement": self.model.uuid,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_application",
                        "replacement": self.model.app.name,
                    },
                    {
                        "source_labels": ["__address__"],
                        "target_label": "juju_unit",
                        "replacement": self.model.unit.name,
                    },
                ],
            },
            "prometheus_remote_write": self._remote_write.endpoints,
            **self._additional_integrations,
        }
        return conf

    @property
    def _loki_config(self) -> Dict[str, List[Any]]:
        """Modifies the loki section of the config.

        Returns:
            a dict with Loki config
        """
        configs = []

        if self._loki_consumer.loki_endpoints:
            configs.append(
                {
                    "name": "push_api_server",
                    "clients": self._loki_consumer.loki_endpoints,
                    "positions": {"filename": self._promtail_positions},
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

        configs.extend(self._additional_log_configs)  # type: ignore
        return {"configs": configs} if configs else {}

    @property
    def _instance_topology(self) -> Dict[str, str]:
        """Return a default topology which may be overridden by children."""
        return {
            "juju_model": self.model.name,
            "juju_model_uuid": self.model.uuid,
            "juju_application": self.model.app.name,
            "juju_unit": self.model.unit.name,
        }

    @property
    def _instance_name(self) -> str:
        """Return the instance name as interpolated topology values."""
        return "_".join([v for v in self._instance_topology.values()])

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
        if not self.is_ready:
            return None
        # Output looks like this:
        # agent, version v0.26.1 (branch: HEAD, revision: 2b88be37)
        result = re.search(r"v(\d*\.\d*\.\d*)", self.agent_version_output())
        if result is None:
            return result
        return result.group(1)
