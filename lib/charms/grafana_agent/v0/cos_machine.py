#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for the cos_machine relation interface."""

import base64
import json
import logging
import lzma
from pathlib import Path
from typing import Dict, List, Optional, Union

# FIXME: unify the alert rules format in cosl to drop these ASAP
from charms.loki_k8s.v0.loki_push_api import AlertRules as LogAlerts
from charms.prometheus_k8s.v0.prometheus_scrape import AlertRules as MetricsAlerts
from ops.charm import RelationEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents

LIBID = ""
LIBAPI = 0
LIBPATCH = 1

PYDEPS = ["cosl"]

DEFAULT_RELATION_NAME = "cos-machine"
DEFAULT_METRICS_ENDPOINT = {
    "path": "/metrics",
    "port": 80,
}

logger = logging.getLogger(__name__)


class CosMachineProvider(Object):
    """Provider class for the cos_machine interface."""

    def __init__(
        self,
        charm,
        relation_name: str = DEFAULT_RELATION_NAME,
        metrics_endpoints: List[dict] = [DEFAULT_METRICS_ENDPOINT],
        metrics_rules_dir: str = "./src/prometheus_alert_rules",
        logs_rules_dir: str = "./src/loki_alert_rules",
        logs_slots: Optional[List[str]] = None,
        dashboard_dirs: List[str] = ["./src/grafana_dashboards"],
        refresh_events: Optional[List] = None,
    ):
        """Create a CosMachineProvider instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            metrics_endpoints: List of endpoints in the form [{"path": path, "port": port}, ...].
            metrics_rules_dir: Directory where the metrics rules are stored.
            logs_rules_dir: Directory where the logs rules are stored.
            logs_slots: Snap slots to connect to for scraping logs
                in the form ["snap-name:slot", ...].
            dashboards_dir: Directory where the dashboards are stored.
            refresh_events: List of events on which to resfresh relation data.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._metrics_endpoints = metrics_endpoints
        self._metrics_rules = metrics_rules_dir
        self._logs_rules = logs_rules_dir
        self._logs_slots = logs_slots or []
        self._dashboard_dirs = dashboard_dirs
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self.update_relation_data)
        self.framework.observe(events.relation_changed, self.update_relation_data)
        for event in self._refresh_events:
            self.framework.observe(event, self.update_relation_data)

    def update_relation_data(self, event):
        """Trigger the class to update relation data."""
        if isinstance(event, RelationEvent):
            relations = [event.relation]
        else:
            relations = self._charm.model.relations[self._relation_name]

        for relation in relations:
            relation.data = self._generate_updated_data()

    def _generate_updated_data(self) -> str:
        """Collate the data for each nested databag and return it."""
        data = {
            "metrics": {
                "scrape_jobs": self._scrape_jobs,
                "alert_rules": self._metrics_alert_rules,
            },
            "logs": {
                "targets": self._logs_slots,
                "alert_rules": self._log_alert_rules,
            },
            # Probably doesn't actually need to be nested
            "dashboards": {
                "dashboards": self._dashboards,
            },
        }

        return json.dumps(data)

    def _scrape_jobs(self) -> List[Dict]:
        """Return a prometheus_scrape-like data structure for jobs."""
        job_name_prefix = self._charm.app.name
        return [
            {"job_name": f"{job_name_prefix}_{key}", **endpoint}
            for key, endpoint in enumerate(self._metrics_endpoints)
        ]

    def _metrics_alert_rules(self) -> Dict:
        """Use (for now) the prometheus_scrape AlertRules to initialize this."""
        alert_rules = MetricsAlerts()
        alert_rules.add_path(self.metrics_rules_dir, recursive=self._recursive)
        return alert_rules.as_dict()

    def _log_alert_rules(self) -> Dict:
        """Use (for now) the loki_push_api AlertRules to initialize this."""
        alert_rules = LogAlerts()
        alert_rules.add_path(self.log_rules_dir, recursive=self._recursive)
        return alert_rules.as_dict()

    def _dashboards(self) -> List[str]:
        dashboards = []
        for d in self._dashboard_dirs:
            for path in Path(d).glob("*"):
                dashboards.append(self._encode_dashboard_content(path.read_bytes()))

        return dashboards

    def _encode_dashboard_content(self, content: Union[str, bytes]) -> str:
        if isinstance(content, str):
            content = bytes(content, "utf-8")

        return base64.b64encode(lzma.compress(content)).decode("utf-8")


class CosMachineDataChanged(EventBase):
    """Event emitted when a `CosMachineProvider` joins or updates data."""


class CosMachineConsumerEvents(ObjectEvents):
    """Event descriptor for events raised by `CosMachineConsumer`."""

    data_changed = EventSource(CosMachineDataChanged)


class CosMachineConsumer(Object):
    """Provider class for the cos_machine interface."""

    on = CosMachineConsumerEvents()

    def __init__(
        self,
        charm,
        relation_name: str = DEFAULT_RELATION_NAME,
        refresh_events: Optional[List] = None,
    ):
        """Create a CosMachineConsumer instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            refresh_events: List of events on which to resfresh relation data.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_data_changed)
        self.framework.observe(events.relation_changed, self._on_relation_data_changed)
        for event in self._refresh_events:
            self.framework.observe(event, self.trigger_refresh)

    def _on_relation_data_changed(self, _):
        self.on.data_changed.emit()

    @property
    def _relations(self):
        return self._charm.model.relations[self._relation_name]

    # Not a property because it isn't in prometheus_scrape, and this keeps the
    # signature compatible from the base class
    def jobs(self) -> List[Dict]:
        """Return a prometheus_scrape-like data structure for jobs."""
        jobs = []
        for relation in self._relations:
            if jobs := relation.data.get("metrics", {}).get("scrape_jobs", []):
                for job in jobs:
                    job_config = {
                        "job_name": job["job_name"],
                        "metrics_path": job["path"],
                        "static_configs": [{"targets": [f"localhost:{job['port']}"]}],
                    }
                jobs.append(json.loads(job_config))

        return jobs

    @property
    def metrics_alerts(self) -> Dict:
        """Fetch metrics alerts."""
        alert_rules = {}
        for relation in self._relations:
            if rules := relation.data.get("metrics", {}).get("alert_rules", []):
                alert_rules.update(json.loads(rules))
        return alert_rules

    @property
    def logs_alerts(self) -> Dict:
        """Fetch log alerts."""
        alert_rules = {}
        for relation in self._relations:
            if rules := relation.data.get("logs", {}).get("alert_rules", []):
                alert_rules.update(json.loads(rules))
        return alert_rules

    @property
    def dashboards(self) -> List[str]:
        """Fetch dashboards as encoded content."""
        dashboards = []
        for relation in self._relations:
            if dashboard := relation.data.get("dashboards", {}).get("dashboards", []):
                dashboards.extend(json.loads(dashboard))
        return dashboards
