#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

r"""## Overview.

This document explains how to use the two principal objects this library provides:


- `LokiPushApiProvider`: This object is meant to be used by any charmed operator that needs to
implement the provider side of the `loki_push_api` relation interface.
For instance a Loki charm.

- `LokiPushApiConsumer`: This object is meant to be used by any charmed operator that needs to
send log to Loki by implementing the consumer side of the `loki_push_api` relation interface.
For instance a Promtail or Grafana agent charm that needs to send logs to Loki.



## LokiPushApiProvider Library Usage

This object may be used by Loki charms to manage relations
with their clients.
For this purposes a Loki charm needs to instantiate the
`LokiPushApiProvider` object providing it with two pieces
of information:

- A reference to the parent (Loki) charm.

- Optionally, the name of the relation that the Loki charm uses to interact
  with its clients. If provided, this relation name must match a provided
  relation in metadata.yaml with the `loki_push_api` interface.
  This argument is not required if your metadata.yaml has precisely one
  provided relation in metadata.yaml with the `loki_push_api` interface, as the
  lib will automatically resolve the relation name inspecting the using the
  meta information of the charm.

An example of this in `metadata.yaml` file should have the following section:

    provides:
      logging:
        interface: loki_push_api

If you would like to use relation name other than `logging`,
you will need to specify the relation name via the `relation_name`
argument when instantiating the :class:`LokiPushApiProvider` object.
However, it is strongly advised to keep the the default relation name,
so that people deploying your charm will have a consistent experience
with all other charms that provide Loki Push API.

For example a Loki charm may instantiate the
`LokiPushApiProvider` in its constructor as follows

    from charms.loki_k8s.v0.loki_push_api import LokiPushApiProvider
    from loki_server import LokiServer
    ...

    class LokiOperatorCharm(CharmBase):
        ...

        def __init__(self, *args):
            super().__init__(*args)
            ...
            self._provide_loki()
            ...

        def _provide_loki(self):
            try:
                version = self._loki_server.version
                self.loki_provider = LokiPushApiProvider(self)
                logger.debug("Loki Provider is available. Loki version: %s", version)
            except LokiServerNotReadyError as e:
                self.unit.status = MaintenanceStatus(str(e))
            except LokiServerError as e:
                self.unit.status = BlockedStatus(str(e))


The `LokiPushApiProvider` object has two main responsibilities:

1.- Be in charge of setting the Loki Push API Address into
relation data so clients can use it to send logs. Every time a unit joins
a relation: `$ juju add-relation loki-k8s loki-client-k8s` the object sets:

    event.relation.data[self.charm.unit]["data"] = self._loki_push_api

Where `self._loki_push_api` is: `http://<LOKI_UNIT_IP>:<LOKI_PORT>/loki/api/v1/push`


2.- Every time a Loki client unit joins a relation set its metadata and
[alerts rules](https://grafana.com/docs/loki/latest/rules/#alerting-rules) to
relation data.

The metadata is stored in relation data:

    event.relation.data[self._charm.app]["metadata"] = json.dumps(self._scrape_metadata)

For instance the metadata has the following data:

    {'model': 'loki',
     'model_uuid': '0b7d1071-ded2-4bf5-80a3-10a81aeb1386',
     'application': 'promtail-k8s'
    }

About alert rules, they are stored in relation data:

    if alert_groups := self._labeled_alert_groups:
        event.relation.data[self._charm.app]["alert_rules"] = json.dumps(
            {"groups": alert_groups}
        )


And has this aspect:

    '{
         "groups": [{
             "name": "loki_0b7d1071-ded2-4bf5-80a3-10a81aeb1386_promtail-k8s_alerts",
             "rules": [{
                 "alert": "HighPercentageError",
                 "expr": "sum(rate({app=\\"foo\\", env=\\"production\\"} |= \\"error\\" [5m]))
                          by (job) \\n  /\\nsum(rate({app=\\"foo\\", env=\\"production\\"}[5m]))
                          by (job)\\n  > 0.05
                          \\n", "for": "10m",
                 "labels": {
                     "severity": "page",
                     "juju_model": "loki",
                     "juju_model_uuid": "0b7d1071-ded2-4bf5-80a3-10a81aeb1386",
                     "juju_application": "promtail-k8s"
                },
                "annotations": {
                    "summary": "High request latency"
               }
             }]
         }]
     }'


Once these alert rules are sent over relation data, the `LokiPushApiProvider` object
stores these files in the directory `/loki/rules` inside the Loki charm container.


## LokiPushApiConsumer Library Usage

This Loki charm interacts with its clients using the Loki
charm library. Charms seeking to send log to Loki,
must do so using the `LokiPushApiConsumer` object from this charm library.
For the simplest use cases, using the `LokiPushApiConsumer` object only requires
instantiating it, typically in the constructor of your charm (the one which
sends logs).

    from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer

    class LokiClientCharm(CharmBase):

        def __init__(self, *args):
            super().__init__(*args)
            ...
            self._loki_consumer = LokiPushApiConsumer(self)


The `LokiPushApiConsumer` constructor requires two things:

- A reference to the parent (LokiClientCharm) charm.

- Optionally, the name of the relation that the Loki charm uses to interact
  with its clients. If provided, this relation name must match a required
  relation in metadata.yaml with the `loki_push_api` interface.
  This argument is not required if your metadata.yaml has precisely one
  required relation in metadata.yaml with the `loki_push_api` interface, as the
  lib will automatically resolve the relation name inspecting the using the
  meta information of the charm

Anytime the relation between a Loki provider charm and a Loki consumer charm is
established a `LokiPushApiEndpointJoined` event is fired. In the consumer side
is it possible to observe this event with:

```python

self.framework.observe(
    self._loki_consumer.on.loki_push_api_endpoint_joined,
    self._on_loki_push_api_endpoint_joined,
)
```

Anytime there are departures in relations between the consumer charm and Loki
the consumer charm is informed, through a `LokiPushApiEndpointDeparted` event, for instance:

```python
self.framework.observe(
    self._loki_consumer.on.loki_push_api_endpoint_departed,
    self._on_loki_push_api_endpoint_departed,
)
```

The consumer charm can then choose to update its configuration in both situations.


## Alerting Rules

This charm library also supports gathering alerting rules from all
related Loki clients charms and enabling corresponding alerts within the
Loki charm. Alert rules are automatically gathered by `LokiPushApiConsumer` object
from a directory conventionally named `loki_alert_rules`.
This directory must reside at the top level in the `src` folder of the
consumer charm. Each file in this directory is assumed to be a single alert rule
in YAML format. The file name must have the `.rule` extension.
The format of this alert rule conforms to the
[Loki docs](https://grafana.com/docs/loki/latest/rules/#alerting-rules).
An example of the contents of one such file is shown below.

```
alert: HighPercentageError
expr: |
  sum(rate({%%juju_topology%%} |= "error" [5m])) by (job)
    /
  sum(rate({%%juju_topology%%}[5m])) by (job)
    > 0.05
for: 10m
labels:
    severity: page
annotations:
    summary: High request latency

```

It is **critical** to use the `%%juju_topology%%` filter in the
expression for the alert rule shown above. This filter is a stub that
is automatically replaced by the `LokiPushApiConsumer` following Loki Client's Juju
topology (application, model and its UUID). Such a topology filter is
essential to ensure that alert rules submitted by one provider charm
generates alerts only for that same charm.  The Loki charm may
be related to multiple Loki client charms. Without this, filter
rules submitted by one provider charm will also result in
corresponding alerts for other provider charms. Hence every alert rule
expression must include such a topology filter stub.

Gathering alert rules and generating rule files within the Loki
charm is easily done using the `alerts()` method of
`LokiPushApiProvider`. Alerts generated by Loki will
automatically include Juju topology labels in the alerts. These labels
indicate the source of the alert. The following labels are
automatically added to every alert

- `juju_model`
- `juju_model_uuid`
- `juju_application`

## Relation Data

The Loki charm uses both application and unit relation data to
obtain information regarding Loki Push API and alert rules.

Units of consumer charm send their alert rules over app relation
data using the `alert_rules` key.

"""

import dataclasses
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Tuple, Union

import yaml
from ops.charm import CharmBase, RelationMeta, RelationRole
from ops.framework import EventBase, EventSource, Object, ObjectEvents, StoredState
from ops.model import BlockedStatus

# The unique Charmhub library identifier, never change it
LIBID = "bf76f23cdd03464b877c52bd1d2f563e"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 5

logger = logging.getLogger(__name__)

RELATION_INTERFACE_NAME = "loki_push_api"
DEFAULT_RELATION_NAME = "logging"
DEFAULT_ALERT_RULES_RELATIVE_PATH = "./src/loki_alert_rules"


class RelationNotFoundError(ValueError):
    """Raised if there is no relation with the given name."""

    def __init__(self, relation_name: str):
        self.relation_name = relation_name
        self.message = f"No relation named '{relation_name}' found"

        super().__init__(self.message)


class RelationInterfaceMismatchError(Exception):
    """Raised if the relation with the given name has a different interface."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_interface: str,
        actual_relation_interface: str,
    ):
        self.relation_name = relation_name
        self.expected_relation_interface = expected_relation_interface
        self.actual_relation_interface = actual_relation_interface
        self.message = (
            f"The '{relation_name}' relation has '{actual_relation_interface}' as "
            f"interface rather than the expected '{expected_relation_interface}'"
        )

        super().__init__(self.message)


class RelationRoleMismatchError(Exception):
    """Raised if the relation with the given name has a different direction."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_role: RelationRole,
        actual_relation_role: RelationRole,
    ):
        self.relation_name = relation_name
        self.expected_relation_interface = expected_relation_role
        self.actual_relation_role = actual_relation_role
        self.message = (
            f"The '{relation_name}' relation has role '{repr(actual_relation_role)}' "
            f"rather than the expected '{repr(expected_relation_role)}'"
        )

        super().__init__(self.message)


def _validate_relation_by_interface_and_direction(
    charm: CharmBase,
    relation_name: str,
    expected_relation_interface: str,
    expected_relation_role: RelationRole,
):
    """Verifies that a relation has the necessary characteristics.

    Verifies that the `relation_name` provided: (1) exists in metadata.yaml,
    (2) declares as interface the interface name passed as `relation_interface`
    and (3) has the right "direction", i.e., it is a relation that `charm`
    provides or requires.

    Args:
        charm: a `CharmBase` object to scan for the matching relation.
        relation_name: the name of the relation to be verified.
        expected_relation_interface: the interface name to be matched by the
            relation named `relation_name`.
        expected_relation_role: whether the `relation_name` must be either
            provided or required by `charm`.

    Raises:
        RelationNotFoundError: If there is no relation in the charm's metadata.yaml
            with the same name as provided via `relation_name` argument.
        RelationInterfaceMismatchError: The relation with the same name as provided
            via `relation_name` argument does not have the same relation interface
            as specified via the `expected_relation_interface` argument.
        RelationRoleMismatchError: If the relation with the same name as provided
            via `relation_name` argument does not have the same role as specified
            via the `expected_relation_role` argument.
    """
    if relation_name not in charm.meta.relations:
        raise RelationNotFoundError(relation_name)

    relation: RelationMeta = charm.meta.relations[relation_name]

    actual_relation_interface = relation.interface_name
    if actual_relation_interface != expected_relation_interface:
        raise RelationInterfaceMismatchError(
            relation_name, expected_relation_interface, actual_relation_interface
        )

    if expected_relation_role == RelationRole.provides:
        if relation_name not in charm.meta.provides:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.provides, RelationRole.requires
            )
    elif expected_relation_role == RelationRole.requires:
        if relation_name not in charm.meta.requires:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.requires, RelationRole.provides
            )
    else:
        raise Exception(f"Unexpected RelationDirection: {expected_relation_role}")


def _is_valid_rule(rule: dict, allow_free_standing: bool) -> bool:
    """This method validates if an alert rule is well formed.

    Args:
        rule: A dictionary containing an alert rule definition

    Returns:
        True if the alert rule is well formed; False otherwise.
    """
    mandatory = ["alert", "expr"]
    if any(field not in rule for field in mandatory):
        return False

    if not allow_free_standing and "%%juju_topology%%" not in rule["expr"]:
        return False

    return True


@dataclasses.dataclass(frozen=True)
class JujuTopology:
    """Dataclass for storing and formatting juju topology information."""

    model: str
    model_uuid: str
    application: str
    charm_name: str

    @staticmethod
    def from_charm(charm):
        """Factory method for creating the topology dataclass from a given charm."""
        return JujuTopology(
            model=charm.model.name,
            model_uuid=charm.model.uuid,
            application=charm.model.app.name,
            charm_name=charm.meta.name,
        )

    @staticmethod
    def from_relation_data(data):
        """Factory method for creating the topology dataclass from a relation data dict."""
        return JujuTopology(
            model=data["model"],
            model_uuid=data["model_uuid"],
            application=data["application"],
            charm_name=data["charm_name"],
        )

    @property
    def identifier(self) -> str:
        """Format the topology information into a terse string."""
        return f"{self.model}_{self.model_uuid}_{self.application}"

    @property
    def short_model_uuid(self):
        """Obtain the short form of the model uuid."""
        return self.model_uuid[:7]

    @property
    def scrape_identifier(self):
        """Format the topology information into a scrape identifier."""
        return "juju_{}_{}_{}".format(
            self.model,
            self.short_model_uuid,
            self.application,
        )

    @property
    def logql_labels(self) -> str:
        """Format the topology information into a verbose string."""
        return 'juju_model="{}", juju_model_uuid="{}", juju_application="{}"'.format(
            self.model, self.model_uuid, self.application
        )

    def as_dict(self, short_uuid=False) -> dict:
        """Format the topology information into a dict."""
        as_dict = dataclasses.asdict(self)
        if short_uuid:
            as_dict["model_uuid"] = self.short_model_uuid
        return as_dict

    def as_dict_with_logql_labels(self):
        """Format the topology information into a dict with keys having 'juju_' as prefix."""
        return {
            "juju_model": self.model,
            "juju_model_uuid": self.model_uuid,
            "juju_application": self.application,
            "juju_charm": self.charm_name,
        }

    def render(self, template: str):
        """Render a juju-topology template string with topology info."""
        return template.replace("%%juju_topology%%", self.logql_labels)


def load_alert_rule_from_file(
    path: Path, topology: JujuTopology, allow_free_standing
) -> Optional[dict]:
    """Load alert rule from a rules file.

    Args:
        path: path to a *.rule file with a single rule ("groups" super section omitted).
        topology: a `JujuTopology` instance.
        allow_free_standing: whether or not to reject files that do not have the special
          %%juju_topology%% template variable, which is the case for free-standing rules.
    """
    with path.open() as rule_file:
        # Load a list of rules from file then add labels and filters
        try:
            rule = yaml.safe_load(rule_file)
            if not _is_valid_rule(rule, allow_free_standing):
                return None
        except Exception as e:
            logger.error("Failed to read alert rules from %s: %s", path.name, e)
            return None
        else:
            # add "juju_" topology labels
            if "labels" not in rule:
                rule["labels"] = {}
            rule["labels"].update(topology.as_dict_with_logql_labels())

            # insert juju topology filters into a Loki alert rule
            rule["expr"] = topology.render(rule["expr"])

            return rule


def load_alert_rules_from_dir(
    dir_path: Union[str, Path],
    topology: JujuTopology,
    *,
    recursive: bool = False,
    allow_free_standing: bool = False,
) -> Tuple[List[dict], List[Path]]:
    """Load alert rules from rule files.

    All rules from files for the same directory are loaded into a single
    group. The generated name of this group includes juju topology.
    By default, only the top directory is scanned; for nested scanning, pass `recursive=True`.

    Args:
        dir_path: directory containing *.rule files (alert rules without groups).
        topology: a `JujuTopology` instance.
        recursive: flag indicating whether to scan for rule files recursively.
        allow_free_standing: whether or not to reject files that do not have the special
          %%juju_topology%% template variable, which is the case for free-standing rules.

    Returns:
        A 2-tuple consisting:
        - a list of prometheus alert rule groups
        - a list of invalid rules files
    """
    alerts = defaultdict(list)

    def _group_name(path) -> str:
        """Generate group name from path and topology.

        The group name is made up of the relative path between the root dir_path, the file path,
        and topology identifier.

        Args:
            path: path to rule file.
        """
        relpath = os.path.relpath(os.path.dirname(path), dir_path)

        # Generate group name:
        #  - name, from juju topology
        #  - suffix, from the relative path of the rule file;
        return (
            f"{topology.identifier}_"
            f"{'' if relpath == '.' else relpath.replace(os.path.sep, '_') + '_'}"
            "alerts"
        )

    invalid_files = []
    for path in filter(Path.is_file, Path(dir_path).glob("**/*.rule" if recursive else "*.rule")):
        if rule := load_alert_rule_from_file(path, topology, allow_free_standing):
            logger.debug("Reading alert rule from %s", path)
            alerts[_group_name(path)].append(rule)
        else:
            invalid_files.append(path)

    # Gather all alerts into a list of groups since Prometheus
    # requires alerts be part of some group
    groups = [{"name": k, "rules": v} for k, v in alerts.items()]
    return groups, invalid_files


def _resolve_dir_against_charm_path(charm: CharmBase, *path_elements: str) -> str:
    """Resolve the provided path items against the directory of the main file.

    Look up the directory of the main .py file being executed. This is normally
    going to be the charm.py file of the charm including this library. Then, resolve
    the provided path elements and return its absolute path, without checking for existence or
     validity.
    """
    charm_dir = Path(charm.charm_dir)
    if not charm_dir.exists() or not charm_dir.is_dir():
        # Operator Framework does not currently expose a robust
        # way to determine the top level charm source directory
        # that is consistent across deployed charms and unit tests
        # Hence for unit tests the current working directory is used
        # TODO: updated this logic when the following ticket is resolved
        # https://github.com/canonical/operator/issues/643
        charm_dir = Path(os.getcwd())

    alerts_dir_path = charm_dir.absolute().joinpath(*path_elements)
    return str(alerts_dir_path)


class NoRelationWithInterfaceFoundError(Exception):
    """No relations with the given interface are found in the charm meta."""

    def __init__(self, charm: CharmBase, relation_interface: str = None):
        self.charm = charm
        self.relation_interface = relation_interface
        self.message = (
            f"No relations with interface '{relation_interface}' found in the meta "
            f"of the '{charm.meta.name}' charm"
        )

        super().__init__(self.message)


class MultipleRelationsWithInterfaceFoundError(Exception):
    """Multiple relations with the given interface are found in the charm meta."""

    def __init__(self, charm: CharmBase, relation_interface: str, relations: list):
        self.charm = charm
        self.relation_interface = relation_interface
        self.relations = relations
        self.message = (
            f"Multiple relations with interface '{relation_interface}' found in the meta "
            f"of the '{charm.name}' charm."
        )

        super().__init__(self.message)


class RelationManagerBase(Object):
    """Base class that represents relation ends ("provides" and "requires").

    :class:`RelationManagerBase` is used to create a relation manager. This is done by inheriting
    from :class:`RelationManagerBase` and customising the sub class as required.

    Attributes:
        name (str): consumer's relation name
    """

    def __init__(self, charm: CharmBase, relation_name):
        super().__init__(charm, relation_name)
        self.name = relation_name


class LokiPushApiEndpointDeparted(EventBase):
    """Event emitted when Loki departed."""


class LokiPushApiEndpointJoined(EventBase):
    """Event emitted when Loki joined."""


class LoggingEvents(ObjectEvents):
    """Event descriptor for events raised by `LokiPushApiProvider`."""

    loki_push_api_endpoint_departed = EventSource(LokiPushApiEndpointDeparted)
    loki_push_api_endpoint_joined = EventSource(LokiPushApiEndpointJoined)


class LokiPushApiProvider(RelationManagerBase):
    """A LokiPushApiProvider class."""

    def __init__(
        self, charm, relation_name: str = DEFAULT_RELATION_NAME, *, rules_dir="/loki/rules"
    ):
        """A Loki service provider.

        Args:
            charm: a `CharmBase` instance that manages this
                instance of the Loki service.

            relation_name: an optional string name of the relation between `charm`
                and the Loki charmed service. The default is "logging".
                It is strongly advised not to change the default, so that people
                deploying your charm will have a consistent experience with all
                other charms that consume metrics endpoints.

        Raises:
            RelationNotFoundError: If there is no relation in the charm's metadata.yaml
                with the same name as provided via `relation_name` argument.
            RelationInterfaceMismatchError: The relation with the same name as provided
                via `relation_name` argument does not have the `loki_push_api` relation
                interface.
            RelationRoleMismatchError: If the relation with the same name as provided
                via `relation_name` argument does not have the `RelationRole.requires`
                role.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.provides
        )
        super().__init__(charm, relation_name)
        self.charm = charm
        self._relation_name = relation_name

        # If Loki is run in single-tenant mode, all the chunks are put in a folder named "fake"
        # https://grafana.com/docs/loki/latest/operations/storage/filesystem/
        # https://grafana.com/docs/loki/latest/rules/#ruler-storage
        tenant_id = "fake"
        self._rules_dir = os.path.join(rules_dir, tenant_id)

        self.container = self.charm.unit.get_container("loki")
        events = self.charm.on[relation_name]
        self.framework.observe(events.relation_changed, self._on_logging_relation_changed)
        self.framework.observe(events.relation_departed, self._on_logging_relation_departed)

    def _on_logging_relation_changed(self, event):
        """Handle changes in related consumers.

        Anytime there are changes in relations between Loki
        and its consumers charms, Loki set the `loki_push_api`
        into the relation data.
        Besides Loki generates alert rules files based what
        consumer charms forwards,

        Args:
            event: a `CharmEvent` in response to which the Loki
                charm must update its relation data.
        """
        if event.relation.data[self.charm.unit].get("data") is None:
            event.relation.data[self.charm.unit].update({"data": self._loki_push_api})
            logger.debug("Saving Loki url in relation data %s", self._loki_push_api)

        if event.relation.data.get(event.relation.app).get("alert_rules") is not None:
            logger.debug("Saving alerts rules to disk")
            self._remove_alert_rules_files(self.container)
            self._generate_alert_rules_files(self.container)

    def _on_logging_relation_departed(self, event):
        """Removes alert rules files when consumer charms left the relation with Loki.

        Args:
            event: a `CharmEvent` in response to which the Loki
                charm must update its relation data.
        """
        if event.relation.data.get(event.relation.app):
            self._remove_alert_rules_files(self.container)

    @property
    def _loki_push_api(self) -> str:
        """Fetch Loki push API URL.

        Returns:
            Loki push API URL as json string
        """
        loki_push_api = f"http://{self.unit_ip}:{self.charm._port}/loki/api/v1/push"
        data = {"loki_push_api": loki_push_api}
        return json.dumps(data)

    @property
    def unit_ip(self) -> str:
        """Returns unit's IP."""
        if bind_address := self.charm.model.get_binding(self._relation_name).network.bind_address:
            return str(bind_address)
        return ""

    def _remove_alert_rules_files(self, container) -> None:
        """Remove alert rules files from workload container.

        Args:
            container: Container which has alert rules files to be deleted
        """
        container.remove_path(self._rules_dir, recursive=True)
        logger.debug("Previous Alert rules files deleted")
        # Since container.remove_path deletes the directory itself with its files
        # we should create it again.
        os.makedirs(self._rules_dir, exist_ok=True)

    def _generate_alert_rules_files(self, container) -> None:
        """Generate and upload alert rules files.

        Args:
            container: Container into which alert rules files are going to be uploaded
        """
        for rel_id, alert_rules in self.alerts().items():
            filename = "{}_rel_{}_alert.rules".format(
                JujuTopology.from_relation_data(alert_rules),
                rel_id,
            )
            path = os.path.join(self._rules_dir, filename)
            rules = yaml.dump({"groups": alert_rules["groups"]})
            container.push(path, rules, make_dirs=True)
            logger.debug("Updated alert rules file %s", filename)

    def alerts(self) -> dict:
        """Fetch alerts for all relations.

        A Loki alert rules file consists of a list of "groups". Each
        group consists of a list of alerts (`rules`) that are sequentially
        executed. This method returns all the alert rules provided by each
        related metrics provider charm. These rules may be used to generate a
        separate alert rules file for each relation since the returned list
        of alert groups are indexed by relation ID. Also for each relation ID
        associated scrape metadata such as Juju model, UUID and application
        name are provided so the a unique name may be generated for the rules
        file. For each relation the structure of data returned is a dictionary
        with four keys

        - groups
        - model
        - model_uuid
        - application

        The value of the `groups` key is such that it may be used to generate
        a Loki alert rules file directly using `yaml.dump` but the
        `groups` key itself must be included as this is required by Loki,
        for example as in `yaml.dump({"groups": alerts["groups"]})`.

        Currently only accepts a list of rules and these
        rules are all placed into a single group, even though Loki itself
        allows for multiple groups within a single alert rules file.

        Returns:
            a dictionary of alert rule groups and associated scrape
            metadata indexed by relation ID.
        """
        alerts = {}
        for relation in self.charm.model.relations[self._relation_name]:
            if not relation.units:
                continue

            alert_rules = json.loads(relation.data[relation.app].get("alert_rules", "{}"))
            metadata = json.loads(relation.data[relation.app].get("metadata", "{}"))

            if alert_rules and metadata:
                try:
                    alerts[relation.id] = JujuTopology.from_relation_data(metadata).as_dict(
                        short_uuid=True
                    )
                    alerts[relation.id].update(groups=alert_rules["groups"])

                except KeyError as e:
                    logger.error(
                        "Relation %s has invalid data: '%s' key is missing",
                        relation.id,
                        e,
                    )

        return alerts


class LokiPushApiConsumer(RelationManagerBase):
    """Loki Consumer class."""

    on = LoggingEvents()
    _stored = StoredState()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        alert_rules_path: str = DEFAULT_ALERT_RULES_RELATIVE_PATH,
        allow_free_standing_rules: bool = False,
    ):
        """Construct a Loki charm client.

        The `LokiPushApiConsumer` object provides configurations to a Loki client charm.
        A charm instantiating this object needs Loki information, for instance the
        Loki API endpoint to push logs.
        The `LokiPushApiConsumer` can be instantiated as follows:

            self._loki_consumer = LokiPushApiConsumer(self)

        Args:
            charm: a `CharmBase` object that manages this `LokiPushApiConsumer` object.
                Typically this is `self` in the instantiating class.
            relation_name: the string name of the relation interface to look up.
                If `charm` has exactly one relation with this interface, the relation's
                name is returned. If none or multiple relations with the provided interface
                are found, this method will raise either an exception of type
                NoRelationWithInterfaceFoundError or MultipleRelationsWithInterfaceFoundError,
                respectively.
            alert_rules_path: an optional path for the location of alert rules
                files. Defaults to "./src/loki_alert_rules",
                resolved from the directory hosting the charm entry file.
                The alert rules are automatically updated on charm upgrade.

        Raises:
            RelationNotFoundError: If there is no relation in the charm's metadata.yaml
                with the same name as provided via `relation_name` argument.
            RelationInterfaceMismatchError: The relation with the same name as provided
                via `relation_name` argument does not have the `loki_push_api` relation
                interface.
            RelationRoleMismatchError: If the relation with the same name as provided
                via `relation_name` argument does not have the `RelationRole.provides`
                role.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.requires
        )
        alert_rules_path = _resolve_dir_against_charm_path(charm, alert_rules_path)
        self.allow_free_standing_rules = allow_free_standing_rules

        super().__init__(charm, relation_name)
        self.topology = JujuTopology.from_charm(charm)

        self._stored.set_default(loki_push_api=None)
        self._charm = charm
        self._relation_name = relation_name
        self._alert_rules_path = alert_rules_path
        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_changed, self._on_logging_relation_changed)
        self.framework.observe(events.relation_departed, self._on_logging_relation_departed)

    def _on_logging_relation_changed(self, event):
        """Handle changes in related consumers.

        Anytime there are changes in the relation between Loki
        and its consumers charms.

        Args:
            event: a `CharmEvent` in response to which the consumer
                charm must update its relation data.
        """
        if not self._charm.unit.is_leader():
            return

        if event.unit is None:
            # Workaround: Seems this is a Juju bug that sends event.unit == None
            # Remove this if when this issue is closed:
            # https://github.com/canonical/loki-operator/issues/3
            return

        if data := event.relation.data[event.unit].get("data"):
            self._stored.loki_push_api = json.loads(data)["loki_push_api"]

        event.relation.data[self._charm.app]["metadata"] = json.dumps(self.topology.as_dict())
        self._set_alert_rules(event)
        self.on.loki_push_api_endpoint_joined.emit()

    def _on_logging_relation_departed(self, _):
        """Handle departures in related consumers.

        Anytime there are departures in relations between the consumer charm and Loki
        the consumer charm is informed, through a `LokiPushApiEndpointDeparted` event.
        The consumer charm can then choose to update its configuration.
        """
        self.on.loki_push_api_endpoint_departed.emit()

    def _set_alert_rules(self, event):
        """Set alert rules into relation data.

        Args:
            event: a `CharmEvent` in response to which the consumer
                charm must update its relation data.
        """
        if alert_groups := self._labeled_alert_groups:
            event.relation.data[self._charm.app]["alert_rules"] = json.dumps(
                {"groups": alert_groups}
            )
        # TODO: else json.dumps({}) ?

    def _label_alert_topology(self, rule) -> dict:
        """Insert juju topology labels into an alert rule.

        Args:
            rule: a dictionary representing a Loki alert rule.

        Returns:
            a dictionary representing Loki alert rule with Juju
            topology labels.
        """
        labels = rule.get("labels", {})
        labels.update(self.topology.as_dict_with_logql_labels())
        rule["labels"] = labels
        return rule

    @property
    def loki_push_api(self):
        """Fetch Loki Push API endpoint sent from LokiPushApiProvider through relation data.

        Returns:
            Loki Push API endpoint
        """
        return self._stored.loki_push_api

    @property
    def _labeled_alert_groups(self) -> list:
        """Load alert rules from rule files.

        All rules from files for a consumer charm are loaded into a single
        group. The generated name of this group includes Juju topology
        prefixes.

        Returns:
            a list of Loki alert rule groups.
        """
        alert_groups, invalid_files = load_alert_rules_from_dir(
            self._alert_rules_path,
            self.topology,
            recursive=False,
            allow_free_standing=self.allow_free_standing_rules,
        )

        if invalid_files:
            must_contain = ["'alert'", "'expr'"]
            if self.allow_free_standing_rules:
                must_contain.append("'%%juju_topology%%'")
            message = "Failed to read alert rules (must contain {}): ".format(
                ", ".join(must_contain)
            ) + ", ".join(map(str, invalid_files))
            self._charm.model.unit.status = BlockedStatus(message)

        elif not alert_groups:
            """No invalid files, but also no alerts found (path might be invalid)"""
            self._charm.model.unit.status = BlockedStatus(
                "No alert rules found in " + self._alert_rules_path
            )

        return alert_groups
