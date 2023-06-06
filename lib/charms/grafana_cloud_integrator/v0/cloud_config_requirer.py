"""Grafana Cloud Integrator Configuration Requirer."""
import logging

from ops.framework import EventBase, EventSource, Object, ObjectEvents


LIBID = "e6f580481c1b4388aa4d2cdf412a47fa"
LIBAPI = 0
LIBPATCH = 3

DEFAULT_RELATION_NAME = "grafana-cloud-config"

logger = logging.getLogger(__name__)


class Credentials:
    def __init__(self, username, password):
        self.username = username
        self.password = password


class CloudConfigAvailableEvent(EventBase):
    """Event emitted when cloud config is available."""

    def __init__(self, handle):
        super().__init__(handle)

class CloudConfigRevokedEvent(EventBase):
    """Event emitted when cloud config is available."""

    def __init__(self, handle):
        super().__init__(handle)

class GrafanaCloudConfigEvents(ObjectEvents):
    """Event descriptor for events raised by `GrafanaCloudConfigRequirer`."""

    cloud_config_available = EventSource(CloudConfigAvailableEvent)
    cloud_config_revoked = EventSource(CloudConfigRevokedEvent)

class GrafanaCloudConfigRequirer(Object):

    on = GrafanaCloudConfigEvents()  # pyright: ignore

    def __init__(self, charm, relation_name = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        
        for event in self._change_events:
            self.framework.observe(event, self._on_relation_changed)

        for event in self._broken_events:
            self.framework.observe(event, self._on_relation_broken)

    def _on_relation_changed(self, event):
        if not self._charm.unit.is_leader():
            return

        if not all(
            self._is_not_empty(x)
            for x in [
                event.relation.data[event.app].get("username", ""),
                event.relation.data[event.app].get("password", ""),
            ]):
                return

        self.on.cloud_config_available.emit()  # pyright: ignore

    def _on_relation_broken(self, event):
        if not self._charm.unit.is_leader():
            return

        self.on.cloud_config_revoked.emit()  # pyright: ignore
    
    def _is_not_empty(self, s):
        return bool(s and not s.isspace())

    @property
    def _change_events(self):
       return [
            self._events.relation_joined,
            self._events.relation_changed,
            self._events.relation_created,
        ]

    @property
    def _broken_events(self):
        return [
            self._events.relation_departed,
            self._events.relation_broken
        ]

    @property
    def _events(self):
        return self._charm.on[self._relation_name]

    @property
    def credentials(self):
        return Credentials(
            self._data.get("username", ""),
            self._data.get("password", "")
        )

    @property
    def loki_ready(self):
        return (
            self._is_not_empty(self.credentials.username)
            and self._is_not_empty(self.credentials.password)
            and self._is_not_empty(self.loki_url))

    @property
    def prometheus_ready(self):
        return (
            self._is_not_empty(self.credentials.username)
            and self._is_not_empty(self.credentials.password)
            and self._is_not_empty(self.prometheus_url))

    @property
    def loki_url(self):
        return self._data.get("loki_url", "")
    
    @property
    def prometheus_url(self):
        return self._data.get("prometheus_url", "")

    @property
    def _data(self):
        for relation in self._charm.model.relations[self._relation_name]:
            logger.info("%s %s %s", relation, self._relation_name, relation.data[relation.app])
            return relation.data[relation.app]
        return {}
