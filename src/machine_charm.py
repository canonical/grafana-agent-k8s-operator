#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from charms.grafana_agent.v0.cos_agent import COSAgentRequirer
from charms.operator_libs_linux.v1 import snap  # type: ignore
from grafana_agent import GrafanaAgentCharm
from ops.main import main
from ops.model import BlockedStatus, MaintenanceStatus, Relation, Unit

logger = logging.getLogger(__name__)

_FsType = str
_MountOption = str
_MountOptions = List[_MountOption]


@dataclass
class _SnapFstabEntry:
    """Representation of an individual fstab entry for snap plugs."""

    source: str
    target: str
    fstype: Union[_FsType, None]
    options: _MountOptions
    dump: int
    fsck: int

    owner: str = field(init=False)
    endpoint_source: str = field(init=False)
    relative_target: str = field(init=False)

    def __post_init__(self):
        """Populate with calculated values at runtime."""
        self.owner = re.sub(
            r"^(.*?)?/snap/(?P<owner>([A-Za-z0-9_-])+)/.*$", r"\g<owner>", self.source
        )
        self.endpoint_source = re.sub(
            r"^(.*?)?/snap/([A-Za-z0-9_-])+/(?P<path>.*$)", r"\g<path>", self.source
        )
        self.relative_target = re.sub(
            r"^(.*?)?/snap/grafana-agent/\d+/shared-logs+(?P<path>/.*$)", r"\g<path>", self.target
        )


@dataclass
class SnapFstab:
    """Build a small representation/wrapper for snap fstab files."""

    fstab_file: Union[Path, str]
    entries: List[_SnapFstabEntry] = field(init=False)

    def __post_init__(self):
        """Populate with calculated values at runtime."""
        self.fstab_file = (
            self.fstab_file if isinstance(self.fstab_file, Path) else Path(self.fstab_file)
        )
        if not self.fstab_file.exists():
            self.entries = []
            return

        entries = []
        for line in self.fstab_file.read_text().split("\n"):
            if not line.strip():
                # skip whitespace-only lines
                continue
            raw_entry = line.split()
            fields = {
                "source": raw_entry[0],
                "target": raw_entry[1],
                "fstype": None if raw_entry[2] == "none" else raw_entry[2],
                "options": raw_entry[3].split(","),
                "dump": int(raw_entry[4]),
                "fsck": int(raw_entry[5]),
            }
            entry = _SnapFstabEntry(**fields)
            entries.append(entry)

        self.entries = entries

    def entry(self, owner: str, endpoint_name: Optional[str]) -> Optional[_SnapFstabEntry]:
        """Find and return a specific entry if it exists."""
        entries = [e for e in self.entries if e.owner == owner]

        if len(entries) > 1 and endpoint_name:
            # If there's more than one entry, the endpoint name may not directly map to
            # the source *or* path. charmed-kafka uses 'logs' as the plug name, and maps
            # .../common/logs to .../log inside Grafana Agent
            #
            # The only meaningful scenario in which this could happen (multiple fstab
            # entries with the same snap "owning" the originating path) is if a snap provides
            # multiple paths as part of the same plug.
            #
            # In this case, for a cheap comparison (rather than implementing some recursive
            # LCS just for this), convert all possible endpoint sources into a list of unique
            # characters, as well as the endpoint name, and build a sequence of entries with
            # a value that's the length of the intersection, the pick the first one i.e. the one
            # with the largest intersection.
            ordered_entries = sorted(
                entries,
                # descending order
                reverse=True,
                # size of the character-level similarity of the two strings
                key=lambda e: len(set(endpoint_name) & set(e.endpoint_source)),
            )
            return ordered_entries[0]

        if len(entries) > 1 or not entries:
            logger.debug(
                "Ambiguous or unknown mountpoint for snap %s at slot %s, not relabeling.",
                owner,
                endpoint_name,
            )
            return None

        return entries[0]


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

    mandatory_relation_pairs = [
        ("cos-agent", ["send-remote-write", "grafana-cloud-config"]),
        ("cos-agent", ["logging-consumer", "grafana-cloud-config"]),
        ("cos-agent", ["grafana-dashboards-provider", "grafana-cloud-config"]),
        ("juju-info", ["send-remote-write", "grafana-cloud-config"]),
        ("juju-info", ["logging-consumer", "grafana-cloud-config"]),
    ]

    def __init__(self, *args):
        super().__init__(*args)
        # technically, only one of 'cos-agent' and 'juju-info' are likely to ever be active at
        # any given time. however, for the sake of understandability, we always set _cos, and
        # we always listen to juju-info-joined events even though one of the two paths will be
        # at all effects unused.
        self._cos = COSAgentRequirer(self)
        self.snap = snap.SnapCache()["grafana-agent"]
        self.framework.observe(
            self._cos.on.data_changed,  # pyright: ignore
            self._on_cos_data_changed,
        )
        self.framework.observe(self._cos.on.validation_error, self._on_cos_validation_error)
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
        self._connect_logging_snap_endpoints()
        self._update_config()
        self._update_status()
        self._update_metrics_alerts()
        self._update_loki_alerts()
        self._update_grafana_dashboards()

    def _on_cos_validation_error(self, event):
        msg_text = "Validation errors for cos-agent relation - check juju debug-log."
        self.status.validation_error = BlockedStatus(msg_text)

        messages = event.message.split("\n")
        for msg in messages[1:]:
            logger.error(msg)

        self._update_status()

    def on_install(self, _event) -> None:
        """Install the Grafana Agent snap."""
        # Check if Grafana Agent is installed
        self.unit.status = MaintenanceStatus("Installing grafana-agent snap")
        try:
            self.snap.ensure(state=snap.SnapState.Latest)
        except snap.SnapError as e:
            raise GrafanaAgentInstallError("Failed to install grafana-agent.") from e

    def _on_start(self, _event) -> None:
        # Ensure the config is up-to-date before we start to avoid racy relation
        # changes and starting with a "bare" config in ActiveStatus
        self._update_config()
        self.unit.status = MaintenanceStatus("Starting grafana-agent snap")

        try:
            self.snap.start(enable=True)
        except snap.SnapError as e:
            raise GrafanaAgentServiceError("Failed to start grafana-agent") from e

        self._update_status()

    def _on_stop(self, _event) -> None:
        self.unit.status = MaintenanceStatus("Stopping grafana-agent snap")
        try:
            self.snap.stop(disable=True)
        except snap.SnapError as e:
            raise GrafanaAgentServiceError("Failed to stop grafana-agent") from e

        self._update_status()

    def _on_remove(self, _event) -> None:
        """Uninstall the Grafana Agent snap."""
        self.unit.status = MaintenanceStatus("Uninstalling grafana-agent snap")
        try:
            self.snap.ensure(state=snap.SnapState.Absent)
        except snap.SnapError as e:
            raise GrafanaAgentInstallError("Failed to uninstall grafana-agent") from e

    def metrics_rules(self) -> Dict[str, Any]:
        """Return a list of metrics rules."""
        return self._cos.metrics_alerts

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        jobs = self._cos.metrics_jobs
        for job in jobs:
            static_configs = job.get("static_configs", [])
            for static_config in static_configs:
                static_config["labels"] = self._principal_labels
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

    def read_file(self, filepath: Union[str, Path]):
        """Read a file's contents.

        Returns:
            A string with the file's contents
        """
        with open(filepath) as f:
            return f.read()

    def write_file(self, path: Union[str, Path], text: str) -> None:
        """Write text to a file.

        Args:
            path: file path to write to
            text: text to write to the file
        """
        with open(path, "w") as f:
            f.write(text)

    def restart(self) -> None:
        """Restart grafana agent."""
        try:
            self.snap.restart()
        except snap.SnapError as e:
            raise GrafanaAgentServiceError("Failed to restart grafana-agent") from e

    @property
    def _is_installed(self) -> bool:
        """Check if the Grafana Agent snap is installed."""
        return self.snap.present

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
                "scrape_configs": [
                    {
                        "job_name": "varlog",
                        "pipeline_stages": [
                            {
                                "drop": {
                                    "expression": ".*file is a directory.*",
                                },
                            },
                        ],
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
                    {
                        "job_name": "syslog",
                        "journal": {"labels": self._principal_labels},
                        "pipeline_stages": [
                            {
                                "drop": {
                                    "expression": ".*file is a directory.*",
                                },
                            },
                        ],
                    },
                ]
                + self._snap_plugs_logging_configs,
            }
        ]

    @property
    def _principal_relation(self) -> Optional[Relation]:
        """The cos-agent relation, if the charm we're related to supports it, else juju-info."""
        # juju relate will do "the right thing" and default to cos-agent, falling back to
        # juju-info if no cos-agent endpoint is available on the principal.
        # Technically, if the charm is executing, there MUST be one of these two relations
        # (otherwise, the subordinate won't even execute). However, for the sake of juju maybe not
        # showing us the relation until after the first few install/start/config-changed, we err on
        # the safe side and type this as Optional.
        return self.model.get_relation("cos-agent") or self.model.get_relation("juju-info")

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

    @property
    def _snap_plugs_logging_configs(self) -> List[Dict[str, Any]]:
        """One logging config for each separate snap connected over the "logs" endpoint."""
        agent_fstab = SnapFstab(Path("/var/lib/snapd/mount/snap.grafana-agent.fstab"))

        shared_logs_configs = []
        for endpoint in self._cos.snap_log_endpoints:
            fstab_entry = agent_fstab.entry(endpoint.owner, endpoint.name)
            target_path = (
                f"{fstab_entry.target}/**"
                if fstab_entry
                else "/snap/grafana-agent/current/shared-logs/**"
            )
            job = {
                "job_name": endpoint.owner,
                "static_configs": [
                    {
                        "targets": ["localhost"],
                        "labels": {
                            "job": endpoint.owner,
                            "__path__": target_path,
                            **{
                                k: v
                                for k, v in self._instance_topology.items()
                                if k not in ["juju_unit", "juju_application"]
                            },
                        },
                    }
                ],
                "pipeline_stages": [
                    {
                        "drop": {
                            "expression": ".*file is a directory.*",
                        },
                    },
                ],
            }

            if fstab_entry:
                job["relabel_configs"] = [
                    {
                        "source_labels": ["__path__"],
                        "target_label": "path",
                        "replacement": fstab_entry.relative_target,
                    }
                ]

            shared_logs_configs.append(job)

        return shared_logs_configs

    def _connect_logging_snap_endpoints(self):
        for plug in self._cos.snap_log_endpoints:
            try:
                self.snap.connect("logs", service=plug.owner, slot=plug.name)
            except snap.SnapError as e:
                logger.error(f"error connecting plug {plug} to grafana-agent:logs")
                logger.error(e.message)

    def positions_dir(self) -> str:
        """Return the positions directory."""
        return "${SNAP_DATA}"


if __name__ == "__main__":
    main(GrafanaAgentMachineCharm)
