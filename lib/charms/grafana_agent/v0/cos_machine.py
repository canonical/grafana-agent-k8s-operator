#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from typing import List

from ops.charm import RelationEvent
from ops.framework import Object

LIBID = ""
LIBAPI = 0
LIBPATCH = 1

DEFAULT_RELATION_NAME = "cos-machine"


class CosMachineProvider(Object):
    """Provider class for the cos_machine interface."""

    def __init__(
        self,
        charm,
        relation_name: str = DEFAULT_RELATION_NAME,
        metrics_endpoints: List[dict] = None,
        metrics_rules_dir: str = None,
        logs_rules_dir: str = None,
        logs_slots: List[str] = None,
        dashboards_dir: List[str] = None,
        refresh_events: list = None,
    ):
        """Create a CosMachineProvider instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            metrics_endpoints: List of endpoints in for form [{"path": path, "port": port}, ...].
            metrics_rules_dir: Directory where the metrics rules are stored.
            logs_rules_dir: Directory where the logs rules are stored.
            logs_slots: Snap slots to connect to for scraping logs.
            dashboards_dir: Directory where the dashboards are stored.
            refresh_events: List of events on which to resfresh relation data.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._metrics_endpoints = metrics_endpoints or []
        self._metrics_rules = metrics_rules_dir
        self._logs_rules = logs_rules_dir
        self._logs_slots = logs_slots or []
        self._dashboards = dashboards_dir or []
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self.update_relation_data)
        for event in self._refresh_events:
            self.framework.observe(event, self.update_relation_data)

    def update_relation_data(self, event):
        if isinstance(event, RelationEvent):
            relations = [event.relation]
        else:
            relations = self._charm.model.relations[self._relation_name]

        for relation in relations:
            self._update_metrics_data(relation)
            self._update_logs_data(relation)
            self._update_dashboards(relation)

    def _update_metrics_data(self, relation):
        rel_data = {}
        rel_data["rules"] = []  # TODO Implement this
        job_name_prefix = self._charm.app.name
        rel_data["jobs"] = [
            {"job_name": f"{job_name_prefix}_{key}", **endpoint}
            for key, endpoint in enumerate(self._metrics_endpoints)
        ]
        relation.data["metrics"] = json.dumps(rel_data)

    def _update_logs_data(self, relation):
        pass  # TODO Implement this

    def _update_dashboards(self, relation):
        pass  # TODO Implement this
