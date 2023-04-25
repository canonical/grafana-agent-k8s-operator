# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Common logic for both k8s and machine charms for Grafana Agent."""
import json
import logging
import os
import pathlib
import re
import shutil
from collections import namedtuple
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import yaml
from charms.grafana_cloud_integrator.v0.cloud_config_requirer import (
    GrafanaCloudConfigRequirer,
)
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import APIError, PathError
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util import Retry  # type: ignore
from yaml.parser import ParserError

logger = logging.getLogger(__name__)

CONFIG_PATH = "/etc/grafana-agent.yaml"
# all these are relative to the charm root
LOKI_RULES_SRC_PATH = "src/loki_alert_rules"
LOKI_RULES_DEST_PATH = "loki_alert_rules"
METRICS_RULES_SRC_PATH = "src/prometheus_alert_rules"
METRICS_RULES_DEST_PATH = "prometheus_alert_rules"
DASHBOARDS_SRC_PATH = "src/grafana_dashboards"
DASHBOARDS_DEST_PATH = "grafana_dashboards"  # placeholder until we figure out the plug

RulesMapping = namedtuple("RulesMapping", ["src", "dest"])


class GrafanaAgentReloadError(Exception):
    """Custom exception to indicate that grafana agent config couldn't be reloaded."""

    def __init__(self, message="could not reload configuration"):
        self.message = message
        super().__init__(self.message)


@dataclass
class CompoundStatus:
    """'Dumb struct' for helping with centralized status setting."""

    # None = good; do not use ActiveStatus here.
    update_config: Optional[Union[BlockedStatus, WaitingStatus]] = None
    validation_error: Optional[StatusBase] = None


class GrafanaAgentCharm(CharmBase):
    """Grafana Agent Charm."""

    _name = "agent"
    _http_listen_port = 3500
    _grpc_listen_port = 3600

    # Pairs of (incoming, [outgoing]) relation names. If any 'incoming' is joined without at least
    # one matching 'outgoing', the charm will block. Without any matching outgoing relation we may
    # incur data loss.
    # Property to facilitate centralized status update.
    # 'outgoing' are OR-ed, 'incoming' are AND-ed.
    mandatory_relation_pairs: List[Tuple[str, List[str]]]  # overridden

    def __new__(cls, *args: Any, **kwargs: Dict[Any, Any]):
        """Forbid the usage of GrafanaAgentCharm directly."""
        if cls is GrafanaAgentCharm:
            raise TypeError("This is a base class and cannot be instantiated directly.")
        return super().__new__(cls)

    def __init__(self, *args):
        super().__init__(*args)

        # Property to facilitate centralized status update
        self.status = CompoundStatus()

        charm_root = self.charm_dir.absolute()
        self.loki_rules_paths = RulesMapping(
            # TODO how to inject topology only for this charm's own rules?
            # FIXED: this is already handled by re-using the *Rules classes
            src=charm_root.joinpath(*LOKI_RULES_SRC_PATH.split("/")),
            dest=charm_root.joinpath(*LOKI_RULES_DEST_PATH.split("/")),
        )
        self.metrics_rules_paths = RulesMapping(
            # TODO how to inject topology only for this charm's own rules?
            # FIXED: this is already handled by re-using the *Rules classes
            src=charm_root.joinpath(*METRICS_RULES_SRC_PATH.split("/")),
            dest=charm_root.joinpath(*METRICS_RULES_DEST_PATH.split("/")),
        )
        self.dashboard_paths = RulesMapping(
            src=charm_root.joinpath(*DASHBOARDS_SRC_PATH.split("/")),
            dest=charm_root.joinpath(*DASHBOARDS_DEST_PATH.split("/")),
        )

        for rules in [self.loki_rules_paths, self.metrics_rules_paths, self.dashboard_paths]:
            if not os.path.isdir(rules.dest):
                shutil.copytree(rules.src, rules.dest, dirs_exist_ok=True)

        self._remote_write = PrometheusRemoteWriteConsumer(
            self, alert_rules_path=self.metrics_rules_paths.dest
        )

        self._loki_consumer = LokiPushApiConsumer(
            self, relation_name="logging-consumer", alert_rules_path=self.loki_rules_paths.dest
        )

        self._grafana_dashboards_provider = GrafanaDashboardProvider(
            self,
            relation_name="grafana-dashboards-provider",
            dashboards_path=self.dashboard_paths.dest,
        )

        self._cloud = GrafanaCloudConfigRequirer(self)

        self.framework.observe(
            self._cloud.on.cloud_config_available,  # pyright: ignore
            self._on_cloud_config_available,
        )
        self.framework.observe(
            self._cloud.on.cloud_config_revoked,  # pyright: ignore
            self._on_cloud_config_revoked,
        )

        self.framework.observe(
            self._grafana_dashboards_provider.on.dashboard_status_changed,  # pyright: ignore
            self._on_dashboard_status_changed,
        )

        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        self.framework.observe(
            self._remote_write.on.endpoints_changed,  # pyright: ignore
            self.on_remote_write_changed,
        )

        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_joined,  # pyright: ignore
            self._on_loki_push_api_endpoint_joined,
        )
        self.framework.observe(
            self._loki_consumer.on.loki_push_api_endpoint_departed,  # pyright: ignore
            self._on_loki_push_api_endpoint_departed,
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        # Register status observers
        for incoming, outgoings in self.mandatory_relation_pairs:
            self.framework.observe(self.on[incoming].relation_joined, self._update_status)
            self.framework.observe(self.on[incoming].relation_broken, self._update_status)
            for outgoing in outgoings:
                self.framework.observe(self.on[outgoing].relation_joined, self._update_status)
                self.framework.observe(self.on[outgoing].relation_broken, self._update_status)

    def _on_mandatory_relation_event(self, _event=None):
        """Event handler for any mandatory relation event."""
        self._update_config()
        self._update_status()

    def _on_upgrade_charm(self, _event=None):
        """Refresh alerts if the charm is updated."""
        self._update_metrics_alerts()
        self._update_loki_alerts()
        self._update_config()
        self._update_status()

    def _on_loki_push_api_endpoint_joined(self, _event=None):
        """Rebuild the config with correct Loki sinks."""
        self._update_config()
        self._update_status()

    def _on_loki_push_api_endpoint_departed(self, _event=None):
        """Rebuild the config with correct Loki sinks."""
        self._update_config()
        self._update_status()

    def _on_config_changed(self, _event=None):
        """Rebuild the config."""
        self._update_config()
        self._update_status()

    def _on_cloud_config_available(self, _) -> None:
        logger.info("cloud config available")
        self._update_config()

    def _on_cloud_config_revoked(self, _) -> None:
        logger.info("cloud config revoked")
        self._update_config()

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

    def metrics_rules(self) -> Dict[str, Any]:
        """Return a list of metrics rules."""
        raise NotImplementedError("Please override the metrics_rules method")

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        raise NotImplementedError("Please override the metrics_jobs method")

    def logs_rules(self) -> Dict[str, Any]:
        """Return a list of logging rules."""
        raise NotImplementedError("Please override the logs_rules method")

    @property
    def dashboards(self) -> list:
        """Return a list of dashboards."""
        raise NotImplementedError("Please override the dashboards method")

    def positions_dir(self) -> str:
        """Return the positions directory."""
        raise NotImplementedError("Please override the positions_dir method")

    # End: Abstract Methods

    def _update_metrics_alerts(self):
        self.update_alerts_rules(
            alerts_func=self.metrics_rules,
            reload_func=self._remote_write.reload_alerts,
            mapping=self.metrics_rules_paths,
        )

    def _update_loki_alerts(self):
        self.update_alerts_rules(
            alerts_func=self.logs_rules,
            reload_func=self._loki_consumer._reinitialize_alert_rules,
            mapping=self.loki_rules_paths,
        )

    def _update_grafana_dashboards(self):
        self.update_dashboards(
            dashboards_func=self.dashboards,
            reload_func=self._grafana_dashboards_provider._update_all_dashboards_from_dir,
            mapping=self.dashboard_paths,
        )

    def _recurse_call_chain(self, maybe_func: Any) -> Dict[str, Any]:
        """Recurse through wrappers until we find a real object, not a Callable."""
        if callable(maybe_func):
            return self._recurse_call_chain(maybe_func())
        return maybe_func

    def update_alerts_rules(self, alerts_func: Any, reload_func: Callable, mapping: RulesMapping):
        """Copy alert rules from relations and save them to disk."""
        # MetricsEndpointConsumer.alerts is not @property, but Loki is, so
        # do the right thing. With an additional layer of indirection, recurse
        # to the bottom until we find a real List|Dict|not-Callable
        rules = self._recurse_call_chain(alerts_func)

        shutil.rmtree(mapping.dest)
        shutil.copytree(mapping.src, mapping.dest)
        for topology_identifier, rule in rules.items():
            file_handle = pathlib.Path(mapping.dest, "juju_{}.rules".format(topology_identifier))
            file_handle.write_text(yaml.dump(rule))
            logger.debug("updated alert rules file {}".format(file_handle.absolute()))
        reload_func()

    def update_dashboards(
        self, dashboards_func: Any, reload_func: Callable, mapping: RulesMapping
    ) -> None:
        """Copy dashboards from relations, save them to disk, and update."""
        try:
            dashboards = dashboards_func
        except NotImplementedError:
            logger.debug("Dashboard forwarding is not yet enabled for k8s grafana-agent")
            return

        shutil.rmtree(mapping.dest)
        shutil.copytree(mapping.src, mapping.dest)
        for dash in dashboards:
            # Build dashboard custom filename
            charm = dash.get("charm", "charm-name")
            rel_id = dash.get("relation_id", "rel_id")
            title = dash.get("title").replace(" ", "_").lower()
            filename = f"juju_{title}-{charm}-{rel_id}.json"

            with open(pathlib.Path(mapping.dest, filename), mode="w", encoding="utf-8") as f:
                f.write(json.dumps(dash["content"]))
                logger.debug("updated dashboard file %s", f.name)

        reload_func()

    def on_scrape_targets_changed(self, _event) -> None:
        """Event handler for the scrape targets changed event."""
        self._update_config()
        self._update_status()
        self._update_metrics_alerts()

    def on_remote_write_changed(self, _event) -> None:
        """Event handler for the remote write changed event."""
        self._update_config()
        self._update_status()
        self._update_metrics_alerts()

    def _update_status(self, *_):
        """Determine the charm status based on relation health and grafana-agent service readiness.

        This is a centralized status setter. Status should only be calculated here, or, if you need
        to temporarily change the status (e.g. during snap install), always call this method after
        so the status is re-calculated (exceptions: on_install, on_remove).
        TODO: Rework this when "compound status" is implemented
         https://github.com/canonical/operator/issues/665
        """
        if not self.is_ready:
            self.unit.status = WaitingStatus("waiting for agent to start")
            return

        if self.status.update_config:
            self.unit.status = self.status.update_config
            return

        if self.status.validation_error:
            self.unit.status = self.status.validation_error
            return

        # Make sure every incoming relation has at least one matching outgoing relation
        for incoming, outgoings in self.mandatory_relation_pairs:
            if not self.model.relations.get(incoming):
                continue

            has_outgoing = any(
                (len(self.model.relations.get(outgoing, [])) for outgoing in outgoings)
            )
            if not has_outgoing:
                missing = "|".join(outgoings)
                logger.warning(
                    "An incoming '%s' relation does not yet have any "
                    "matching outgoing relation(s): [%s]",
                    incoming,
                    missing,
                )
                self.unit.status = BlockedStatus(f"Missing relation: [{missing}]")
                return

        if not self.is_ready:
            self.unit.status = WaitingStatus("waiting for the agent to start")
            return

        self.unit.status = ActiveStatus()

    def _update_config(self) -> None:
        if not self.is_ready:
            # Grafana-agent is not yet available so no need to update config
            return

        config = self._generate_config()

        try:
            old_config = yaml.safe_load(self.read_file(CONFIG_PATH))
        except (FileNotFoundError, PathError, ParserError):
            # File does not yet exist? Processing a deferred event?
            old_config = None

        if config == old_config:
            # Nothing changed, possibly new installation. Move on.
            self.status.update_config = None
            return

        try:
            self.write_file(CONFIG_PATH, yaml.dump(config))
            # FIXME: change this to self._reload_config when #19 is fixed
            # Restart the service to pick up the new config
            self.restart()
        except GrafanaAgentReloadError as e:
            logger.error(str(e))
            self.status.update_config = BlockedStatus(str(e))
        except APIError as e:
            logger.warning(str(e))
            self.status.update_config = WaitingStatus(str(e))

        self.status.update_config = None

    def _on_dashboard_status_changed(self, _event=None):
        """Re-initialize dashboards to forward."""
        # TODO: add constructor arg for `inject_dropdowns=False` instead of 'private' method?
        self._grafana_dashboards_provider._reinitialize_dashboard_data(
            inject_dropdowns=False
        )  # noqa
        self._update_status()

    def _enrich_endpoints(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Add TLS information to Prometheus and Loki endpoints."""
        prometheus_endpoints: List[Dict[str, Any]] = self._remote_write.endpoints

        if self._cloud.prometheus_ready:
            prometheus_endpoints.append(
                {
                    "url": self._cloud.prometheus_url,
                    "basic_auth": {
                        "username": self._cloud.credentials.username,
                        "password": self._cloud.credentials.password,
                    },
                }
            )

        loki_endpoints = self._loki_consumer.loki_endpoints

        if self._cloud.loki_ready:
            loki_endpoints.append(
                {
                    "url": self._cloud.loki_url,
                    "basic_auth": {
                        "username": self._cloud.credentials.username,
                        "password": self._cloud.credentials.password,
                    },
                }
            )

        for endpoint in prometheus_endpoints + loki_endpoints:
            endpoint["tls_config"] = {
                "insecure_skip_verify": self.model.config.get("tls_insecure_skip_verify")
            }
        return prometheus_endpoints, loki_endpoints

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
        prometheus_endpoints, _ = self._enrich_endpoints()

        config = {
            "server": {"log_level": "info"},
            "integrations": self._integrations_config,
            "metrics": {
                "wal_directory": "/tmp/agent/data",
                "configs": [
                    {
                        "name": "agent_scraper",
                        "scrape_configs": self.metrics_jobs(),
                        "remote_write": prometheus_endpoints,
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

        prometheus_endpoints, _ = self._enrich_endpoints()

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
            "prometheus_remote_write": prometheus_endpoints,
            **self._additional_integrations,
        }
        return conf

    @property
    def _loki_config(self) -> Dict[str, Union[Any, List[Any]]]:
        """Modifies the loki section of the config.

        Returns:
            a dict with Loki config
        """
        _, loki_endpoints = self._enrich_endpoints()

        configs = []
        if self._loki_consumer.loki_endpoints:
            configs.append(
                {
                    "name": "push_api_server",
                    "clients": loki_endpoints,
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
        return (
            {
                "positions_directory": f"{self.positions_dir()}/grafana-agent-positions",
                "configs": configs,
            }
            if configs
            else {}
        )

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
        return "_".join(list(self._instance_topology.values()))

    def _reload_config(self, attempts: int = 10) -> None:
        """Reload the config file.

        Args:
            attempts: number of attempts to reload

        Raises:
            GrafanaAgentReloadError: if configuration could not be reloaded.
        """
        try:
            logger.debug("reloading agent configuration")
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
