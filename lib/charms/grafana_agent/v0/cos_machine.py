# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

r"""## Overview.

This library can be used to manage the cos_machine relation interface:

- `COSMachineProvider`: Use in machine charms that need to have a workload's metrics
  or logs scraped, or forward rule files or dashboards to Prometheus, Loki or Grafana through
  the Grafana Agent machine charm.

- `COSMachineConsumer`: Used in the Grafana Agent machine charm to manage the requrier side of 
  the `cos_machine` interface.


## COSMachineProvider Library Usage

Grafana Agent machine Charmed Operator interacts with its clients using the cos_machine library.
Charms seeking to send telemetry, must do so using the `COSMachineProvider` object from
this charm library.

Using the `COSMachineProvider` object only requires instantiating it,
typically in the `__init__` method of your charm (the one which sends telemetry).

The constructor of `COSMachineProvider` has only one required and eight optional parameters:

```python
    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        metrics_endpoints: Optional[List[dict]] = None,
        metrics_rules_dir: str = "./src/prometheus_alert_rules",
        logs_rules_dir: str = "./src/loki_alert_rules",
        recurse_rules_dirs: bool = False,
        log_slots: Optional[List[str]] = None,
        dashboard_dirs: Optional[List[str]] = None,
        refresh_events: Optional[List] = None,
    ):
```

### Paramenters

- `charm`: The instance of the charm that instantiates `COSMachineProvider`, tipically `self`.

- `relation_name`: If your charmed operator uses a relation name other than `cos-machine` to use
    the `cos_machine` interface, this is where you have to specify that.

- `metrics_endpoints`: In this parameter you can specify the metrics endpoints that Grafana Agent
    machine Charmed Operator will scrape.

- `metrics_rules_dir`: The directory in which the Charmed Operator stores its metrics alert rules files.

- `logs_rules_dir`: The directory in which the Charmed Operator stores its logs alert rules files.

- `recurse_rules_dirs`: This paramenters set wheter Grafana Agent machine Charmed Operator has to search
    alert rules files recursively in the previous two directories or not.

- `log_slots`: Snap slots to connect to for scraping logs in the form ["snap-name:slot", ...].

- `dashboard_dirs`: List of directories where the dashboards are stored in the Charmed Operator.

- `refresh_events`: List of events on which to refresh relation data.


### Example 1 - Minimal instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_machine import COSMachineProvider
...
class TelemetryProviderCharm(CharmBase):
    def __init__(self, *args):
        ...
        self._grafana_agent = COSMachineProvider(self)
```

### Example 2 - Full instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_machine import COSMachineProvider
...
class TelemetryProviderCharm(CharmBase):
    def __init__(self, *args):
        ...
        self._grafana_agent = COSMachineProvider(
            self,
            relation_name="custom-cos-machine",
            metrics_endpoints=[
                {"path": "/metrics", "port": 9000},
                {"path": "/metrics", "port": 9001},
                {"path": "/metrics", "port": 9002},
            ],
            metrics_rules_dir="./src/alert_rules/prometheus",
            logs_rules_dir="./src/alert_rules/loki",
            recursive_rules_dir=True,
            log_slots=["my-app:slot"],
            dashboard_dirs=["./src/dashboards_1", "./src/dashboards_2"],
            refresh_events=["update-status", "upgrade-charm"],
        )
```

## COSMachineConsumer Library Usage

This object may be used by any Charmed Operator which gathers telemetry data by
implementing the consumer side of the `cos_machine` interface.
For instance Grafana Agent machine Charmed Operator.

For this purposes the charm needs to instantiate the `COSMachineConsumer` object with one mandatory
and two optional arguments.

### Paramenters

- `charm`: A reference to the parent (Grafana Agent machine) charm.

- `relation_name`: The name of the relation that the charm uses to interact
  with its clients that provides telemetry data using the `COSMachineProvider` object.

  If provided, this relation name must match a provided relation in metadata.yaml with the
  `cos_machine` interface.
  The default value of this arguments is "cos-machine".

- `refresh_events`: List of events on which to refresh relation data.


### Example 1 - Minimal instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_machine import COSMachineConsumer
...
class GrafanaAgentMachineCharm(GrafanaAgentCharm)
    def __init__(self, *args):
        ...
        self._cos = COSMachineRequirer(self)
```


### Example 2 - Full instrumentation:

In order to use this object the following should be in the `charm.py` file.

```python
from charms.grafana_agent.v0.cos_machine import COSMachineConsumer
...
class GrafanaAgentMachineCharm(GrafanaAgentCharm)
    def __init__(self, *args):
        ...
        self._cos = COSMachineRequirer(
            self,
            relation_name="cos-machine-consumer",
            refresh_events=["update-status", "upgrade-charm"],
        )
```
"""

import base64
import json
import logging
import lzma
from collections import namedtuple
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from cosl import JujuTopology
from cosl.rules import AlertRules
from ops.charm import RelationEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation
from ops.testing import CharmType

LIBID = "1212"  # FIXME: Need to get a valid ID from charmhub
LIBAPI = 0
LIBPATCH = 1

PYDEPS = ["cosl"]

DEFAULT_RELATION_NAME = "cos-machine"
DEFAULT_METRICS_ENDPOINT = {
    "path": "/metrics",
    "port": 80,
}

logger = logging.getLogger(__name__)
SnapEndpoint = namedtuple("SnapEndpoint", "owner, name")


class COSMachineProvider(Object):
    """Integration endpoint wrapper for the provider side of the cos_machine interface."""

    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        metrics_endpoints: Optional[List[dict]] = None,
        metrics_rules_dir: str = "./src/prometheus_alert_rules",
        logs_rules_dir: str = "./src/loki_alert_rules",
        recurse_rules_dirs: bool = False,
        log_slots: Optional[List[str]] = None,
        dashboard_dirs: Optional[List[str]] = None,
        refresh_events: Optional[List] = None,
    ):
        """Create a COSMachineProvider instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            metrics_endpoints: List of endpoints in the form [{"path": path, "port": port}, ...].
            metrics_rules_dir: Directory where the metrics rules are stored.
            logs_rules_dir: Directory where the logs rules are stored.
            recurse_rules_dirs: Whether or not to recurse into rule paths.
            log_slots: Snap slots to connect to for scraping logs
                in the form ["snap-name:slot", ...].
            dashboard_dirs: Directory where the dashboards are stored.
            refresh_events: List of events on which to refresh relation data.
        """
        super().__init__(charm, relation_name)
        metrics_endpoints = metrics_endpoints or [DEFAULT_METRICS_ENDPOINT]
        dashboard_dirs = dashboard_dirs or ["./src/grafana_dashboards"]

        self._charm = charm
        self._relation_name = relation_name
        self._metrics_endpoints = metrics_endpoints
        self._metrics_rules = metrics_rules_dir
        self._logs_rules = logs_rules_dir
        self._recursive = recurse_rules_dirs
        self._log_slots = log_slots or []
        self._dashboard_dirs = dashboard_dirs
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_refresh)
        self.framework.observe(events.relation_changed, self._on_refresh)
        for event in self._refresh_events:
            self.framework.observe(event, self._on_refresh)

    def _on_refresh(self, event):
        """Trigger the class to update relation data."""
        if isinstance(event, RelationEvent):
            relations = [event.relation]
        else:
            relations = self._charm.model.relations[self._relation_name]

        for relation in relations:
            if relation.data:
                relation.data[self._charm.app].update({"config": self._generate_databag_content()})

    def _generate_databag_content(self) -> str:
        """Collate the data for each nested databag and return it."""
        # The databag is divided in three chunks: metrics, logs, and dashboards.

        data = {
            # primary key
            "metrics": {
                # secondary key
                "scrape_jobs": self._scrape_jobs,
                "alert_rules": self._metrics_alert_rules,
            },
            "logs": {
                "targets": self._log_slots,
                "alert_rules": self._log_alert_rules,
            },
            "dashboards": {
                "dashboards": self._dashboards,
            },
        }

        return json.dumps(data)

    @property
    def _scrape_jobs(self) -> List[Dict]:
        """Return a prometheus_scrape-like data structure for jobs."""
        job_name_prefix = self._charm.app.name
        return [
            {"job_name": f"{job_name_prefix}_{key}", **endpoint}
            for key, endpoint in enumerate(self._metrics_endpoints)
        ]

    @property
    def _metrics_alert_rules(self) -> Dict:
        """Use (for now) the prometheus_scrape AlertRules to initialize this."""
        alert_rules = AlertRules(
            query_type="promql", topology=JujuTopology.from_charm(self._charm)
        )
        alert_rules.add_path(self._metrics_rules, recursive=self._recursive)
        return alert_rules.as_dict()

    @property
    def _log_alert_rules(self) -> Dict:
        """Use (for now) the loki_push_api AlertRules to initialize this."""
        alert_rules = AlertRules(query_type="logql", topology=JujuTopology.from_charm(self._charm))
        alert_rules.add_path(self._logs_rules, recursive=self._recursive)
        return alert_rules.as_dict()

    @property
    def _dashboards(self) -> List[str]:
        dashboards = []
        for d in self._dashboard_dirs:
            for path in Path(d).glob("*"):
                dashboards.append(self._encode_dashboard_content(path.read_bytes()))

        return dashboards

    @staticmethod
    def _encode_dashboard_content(content: Union[str, bytes]) -> str:
        if isinstance(content, str):
            content = bytes(content, "utf-8")

        return base64.b64encode(lzma.compress(content)).decode("utf-8")


class COSMachineDataChanged(EventBase):
    """Event emitted by `COSMachineRequirer` when relation data changes."""


class COSMachineRequirerEvents(ObjectEvents):
    """`COSMachineRequirer` events."""

    data_changed = EventSource(COSMachineDataChanged)


class COSMachineRequirer(Object):
    """Integration endpoint wrapper for the Requirer side of the cos_machine interface."""

    on = COSMachineRequirerEvents()

    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        refresh_events: Optional[List[str]] = None,
    ):
        """Create a COSMachineRequirer instance.

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

    def trigger_refresh(self, _):
        """Trigger a refresh of relation data."""
        # FIXME: Figure out what we should do here
        self.on.data_changed.emit()

    @property
    def _relations(self):
        return self._charm.model.relations[self._relation_name]

    @staticmethod
    def _fetch_data_from_relation(relation: Relation, primary_key: str, secondary_key: str):
        """Extract data by path from a relation's app data."""
        # ensure that whatever context we're running this in, we take the necessary precautions:
        if not relation.data or not relation.app:
            return None

        config = json.loads(relation.data[relation.app].get("config", "{}"))
        return config.get(primary_key, {}).get(secondary_key, None)

    @property
    def metrics_alerts(self) -> Dict[str, Any]:
        """Fetch metrics alerts."""
        alert_rules = {}
        for relation in self._relations:
            # This is only used for naming the file, so be as specific as we
            # can be, but it's ok if the unit name isn't exactly correct, so
            # long as we don't dedupe away the alerts, which will be
            identifier = JujuTopology(
                model=self._charm.model.name,
                model_uuid=self._charm.model.uuid,
                application=relation.app.name if relation.app else "unknown",
                unit=self._charm.unit.name,
            ).identifier
            if data := self._fetch_data_from_relation(relation, "metrics", "alert_rules"):
                alert_rules.update({identifier: data})
        return alert_rules

    @property
    def metrics_jobs(self) -> List[Dict]:
        """Parse the relation data contents and extract the metrics jobs."""
        scrape_jobs = []
        for relation in self._relations:
            if jobs := self._fetch_data_from_relation(relation, "metrics", "scrape_jobs"):
                for job in jobs:
                    job_config = {
                        "job_name": job["job_name"],
                        "metrics_path": job["path"],
                        "static_configs": [{"targets": [f"localhost:{job['port']}"]}],
                    }
                    scrape_jobs.append(job_config)

        return scrape_jobs

    @property
    def snap_log_endpoints(self) -> List[SnapEndpoint]:
        """Fetch logging endpoints exposed by related snaps."""
        plugs = []
        for relation in self._relations:
            if targets := self._fetch_data_from_relation(relation, "logs", "targets"):
                for target in targets:
                    if target in plugs:
                        logger.warning(
                            f"plug {target} already listed. "
                            "The same snap is being passed from multiple "
                            "endpoints; this should not happen."
                        )
                    else:
                        plugs.append(target)

        endpoints = []
        for plug in plugs:
            if ":" not in plug:
                logger.error(f"invalid plug definition received: {plug}. Ignoring...")
            else:
                endpoint = SnapEndpoint(*plug.split(":"))
                endpoints.append(endpoint)
        return endpoints

    @property
    def logs_alerts(self) -> Dict[str, Any]:
        """Fetch log alerts."""
        alert_rules = {}
        for relation in self._relations:
            # This is only used for naming the file, so be as specific as we
            # can be, but it's ok if the unit name isn't exactly correct, so
            # long as we don't dedupe away the alerts, which will be
            identifier = JujuTopology(
                model=self._charm.model.name,
                model_uuid=self._charm.model.uuid,
                application=relation.app.name if relation.app else "unknown",
                unit=self._charm.unit.name,
            ).identifier
            if rules := self._fetch_data_from_relation(relation, "logs", "alert_rules"):
                alert_rules.update({identifier: rules})
        return alert_rules

    @property
    def dashboards(self) -> List[Dict[str, str]]:
        """Fetch dashboards as encoded content."""
        dashboards = []  # type: List[Dict[str, str]]
        for relation in self._relations:
            if dashboard_data := self._fetch_data_from_relation(
                relation, "dashboards", "dashboards"
            ):
                for dashboard in dashboard_data:
                    dashboards.append(
                        {
                            "relation_id": str(relation.id),
                            # We don't have the remote charm name, but give us an identifier
                            "charm": f"{relation.name}-{relation.app.name if relation.app else 'unknown'}",
                            "content": self._decode_dashboard_content(dashboard),
                        }
                    )
        return dashboards

    @staticmethod
    def _decode_dashboard_content(encoded_content: str) -> str:
        return lzma.decompress(base64.b64decode(encoded_content.encode("utf-8"))).decode()
