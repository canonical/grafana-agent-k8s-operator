#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""
import logging
import pathlib
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Union

from charms.grafana_agent.v0.cos_machine import COSMachineRequirer
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, Relation, Unit

from grafana_agent import GrafanaAgentCharm

logger = logging.getLogger(__name__)


class GrafanaAgentError(Exception):
    """Custom exception type for Grafana Agent."""

    pass


class GrafanaAgentInstallError(GrafanaAgentError):
    """Custom exception type for install related errors."""

    pass


class GrafanaAgentServiceError(GrafanaAgentError):
    """Custom exception type for service related errors."""

    pass


class GrafanaAgentMachineCharm(GrafanaAgentCharm):
    """Machine version of the Grafana Agent charm."""

    service_name = "grafana-agent.grafana-agent"

    def __init__(self, *args):
        super().__init__(*args)
        # technically, only one of 'cos-machine' and 'juju-info' are likely to ever be active at
        # any given time. however, for the sake of understandability, we always set _cos, and
        # we always listen to juju-info-joined events even though one of the two paths will be
        # at all effects unused.
        self._cos = COSMachineRequirer(self)
        self.framework.observe(self._cos.on.data_changed, self._on_cos_data_changed)
        self.framework.observe(self.on["juju_info"].relation_joined, self._on_juju_info_joined)

        self.framework.observe(self.on.install, self.on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.remove, self._on_remove)

    def _on_juju_info_joined(self, _event):
        """Update the config when Juju info is joined."""
        self._update_config()
        self._update_status()

    def _on_cos_data_changed(self, _event):
        """Trigger renewals of all data if there is a change."""
        self._update_config()
        self._update_status()
        self._update_metrics_alerts()
        self._update_loki_alerts()
        self._update_snap_logs()
        self._update_grafana_dashboards()  # TODO rbarry check this

    def on_install(self, _event) -> None:
        """Install the Grafana Agent snap."""
        # Check if Grafana Agent is installed
        self.unit.status = MaintenanceStatus("Installing grafana-agent snap")
        if not self._is_installed:
            subprocess.run(["sudo", "snap", "install", "grafana-agent"])
            if not self._is_installed:
                raise GrafanaAgentInstallError("Failed to install grafana-agent.")

    def _on_start(self, _event) -> None:
        # Ensure the config is up-to-date before we start to avoid racy relation
        # changes and starting with a "bare" config in ActiveStatus
        self._update_config()
        self.unit.status = MaintenanceStatus("Starting grafana-agent snap")
        start_process = subprocess.run(["sudo", "snap", "start", "--enable", self.service_name])
        if start_process.returncode != 0:
            raise GrafanaAgentServiceError("Failed to start grafana-agent")
        self.unit.status = ActiveStatus("")

    def _on_stop(self, _event) -> None:
        self.unit.status = MaintenanceStatus("Stopping grafana-agent snap")
        stop_process = subprocess.run(["sudo", "snap", "stop", "--disable", self.service_name])
        if stop_process.returncode != 0:
            raise GrafanaAgentServiceError("Failed to stop grafana-agent")

    def _on_remove(self, _event) -> None:
        """Uninstall the Grafana Agent snap."""
        self.unit.status = MaintenanceStatus("Uninstalling grafana-agent snap")
        subprocess.run(["sudo", "snap", "remove", "--purge", "grafana-agent"])
        if self._is_installed:
            raise GrafanaAgentInstallError("Failed to uninstall grafana-agent")

    def metrics_rules(self) -> Dict[str, Any]:
        """Return a list of metrics rules."""
        return self._cos.metrics_alerts

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        jobs = self._cos.metrics_jobs
        for job in jobs:
            job["labels"] = self._principal_labels
        return jobs

    def logs_rules(self) -> Dict[str, Any]:
        """Return a list of logging rules."""
        return self._cos.logs_alerts

    @property
    def dashboards(self) -> list:
        """Return a list of dashboards."""
        return self._cos.dashboards

    @property
    def is_ready(self) -> bool:
        """Checks if the charm is ready for configuration."""
        return self._is_installed

    def agent_version_output(self) -> str:
        """Runs `agent -version` and returns the output.

        Returns:
            Output of `agent -version`
        """
        return subprocess.run(["/bin/agent", "-version"], capture_output=True, text=True).stdout

    def read_file(self, filepath: Union[str, pathlib.Path]):
        """Read a file's contents.

        Returns:
            A string with the file's contents
        """
        with open(filepath) as f:
            return f.read()

    def write_file(self, path: Union[str, pathlib.Path], text: str) -> None:
        """Write text to a file.

        Args:
            path: file path to write to
            text: text to write to the file
        """
        with open(path, "w") as f:
            f.write(text)

    def restart(self) -> None:
        """Restart grafana agent."""
        subprocess.run(["sudo", "snap", "restart", self.service_name])

    @property
    def _is_installed(self) -> bool:
        """Check if the Grafana Agent snap is installed."""
        package_check = subprocess.run("snap list grafana-agent", shell=True)
        return package_check.returncode == 0

    @property
    def _additional_integrations(self) -> Dict[str, Any]:
        """Additional integrations for machine charms."""
        node_exporter_job_name = (
            f"juju_{self.model.name}_{self.model.uuid}_{self.model.app.name}_node-exporter"
        )
        return {
            "node_exporter": {
                "enabled": True,
                "relabel_configs": [
                    # Align the "job" name with those of prometheus_scrape
                    {
                        "target_label": "job",
                        "regex": "(.*)",
                        "replacement": node_exporter_job_name,
                    },
                ]
                + self._principal_relabeling_config,
            }
        }

    @property
    def _additional_log_configs(self) -> List[Dict[str, Any]]:
        """Additional logging configuration for machine charms."""
        _, loki_endpoints = self._enrich_endpoints()
        return [
            {
                "name": "log_file_scraper",
                "clients": loki_endpoints,
                "positions": {"filename": self._promtail_positions},
                "scrape_configs": [
                    {
                        "job_name": "varlog",
                        "static_configs": [
                            {
                                "targets": ["localhost"],
                                "labels": {
                                    "__path__": "/var/log/*log",
                                    **self._principal_labels,
                                },
                            }
                        ],
                    },
                    {"job_name": "syslog", "journal": {"labels": self._principal_labels}},
                ],
            }
        ]

    @property
    def _principal_relation(self) -> Optional[Relation]:
        """The cos-machine relation, if the charm we're related to supports it, else juju-info."""
        # juju relate will do "the right thing" and default to cos-machine, falling back to
        # juju-info if no cos-machine endpoint is available on the principal.
        # Technically, if the charm is executing, there MUST be one of these two relations
        # (otherwise, the subordinate won't even execute). However, for the sake of juju maybe not
        # showing us the relation until after the first few install/start/config-changed, we err on
        # the safe side and type this as Optional.
        return self.model.get_relation("cos-machine") or self.model.get_relation("juju-info")

    @property
    def principal_unit(self) -> Optional[Unit]:
        """Return the principal unit this charm is subordinated to."""
        relation = self._principal_relation
        if relation and relation.units:
            # Here, we could have popped the set and put the unit back or
            # memoized the function, but in the interest of backwards compatibility
            # with older python versions and avoiding adding temporary state to
            # the charm instance, we choose this somewhat unsightly option.
            return next(iter(relation.units))
        return None

    @property
    def _instance_topology(
        self,
    ) -> Dict[str, str]:
        unit = self.principal_unit
        if unit:
            # Note we can't include juju_charm as that information is not available to us.
            return {
                "juju_model": self.model.name,
                "juju_model_uuid": self.model.uuid,
                "juju_application": unit.app.name,
                "juju_unit": unit.name,
            }
        else:
            return {}

    @property
    def _principal_labels(self) -> Dict[str, str]:
        """Return a dict with labels from the topology of the principal charm."""
        return {
            # Dict ordering will give the appropriate result here
            "instance": self._instance_name,
            **self._instance_topology,
        }

    @property
    def _principal_relabeling_config(self) -> list:
        """Return a relabelling config with labels from the topology of the principal charm."""
        topology_relabels = (
            [
                {
                    "source_labels": ["__address__"],
                    "target_label": key,
                    "replacement": value,
                }
                for key, value in self._instance_topology.items()
            ]
            if self._principal_labels
            else []
        )

        return [
            {
                "target_label": "instance",
                "regex": "(.*)",
                "replacement": self._instance_name,
            }
        ] + topology_relabels  # type: ignore

    def _update_snap_logs(self):
        for plug in self._cos.snap_log_plugs:
            cmd = f"sudo snap connect {plug} grafana-agent:logs"
            try:
                subprocess.check_output(shlex.split(cmd))
            except subprocess.CalledProcessError:
                logger.error(f"error connecting plug {plug} to grafana-agent:logs", exc_info=True)
        # TODO: figure out if we need to do anything to add the new log dirs/files to the tail


if __name__ == "__main__":
    main(GrafanaAgentMachineCharm)
