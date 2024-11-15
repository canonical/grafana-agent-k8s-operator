"""Grafana Cloud Integrator Configuration Requirer."""

import logging

from ops.framework import EventBase, EventSource, Object, ObjectEvents

LIBID = "e6f580481c1b4388aa4d2cdf412a47fa"
LIBAPI = 0
LIBPATCH = 8

DEFAULT_RELATION_NAME = "grafana-cloud-config"

logger = logging.getLogger(__name__)


class Credentials:
    """Credentials for the remote endpoints."""

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
    """Requirer side of the Grafana Cloud Config relation."""

    on = GrafanaCloudConfigEvents()  # pyright: ignore

    def __init__(self, charm, relation_name=DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        for event in self._change_events:
            self.framework.observe(event, self._on_relation_changed)

        for event in self._broken_events:
            self.framework.observe(event, self._on_relation_broken)

    def _on_relation_changed(self, event):
        self.on.cloud_config_available.emit()  # pyright: ignore

    def _on_relation_broken(self, event):
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
        return [self._events.relation_departed, self._events.relation_broken]

    @property
    def _events(self):
        return self._charm.on[self._relation_name]

    @property
    def credentials(self):
        """Return the credentials, if any; otherwise, return None."""
        if (username := self._data.get("username", "").strip()) and (
            password := self._data.get("password", "").strip()
        ):
            return Credentials(username, password)
        return None

    @property
    def loki_ready(self):
        """Check whether there is a non-empty Loki url in relation data."""
        return self._is_not_empty(self.loki_url)

    @property
    def loki_endpoint(self) -> dict:
        """Return the loki endpoint dict."""
        if not self.loki_ready:
            return {}

        endpoint = {}
        endpoint["url"] = self.loki_url
        if self.credentials:
            endpoint["basic_auth"] = {
                "username": self.credentials.username,
                "password": self.credentials.password,
            }
        return endpoint

    @property
    def prometheus_ready(self):
        """Check whether there is a non-empty Prometheus url in relation data."""
        return self._is_not_empty(self.prometheus_url)

    @property
    def tempo_ready(self):
        """Check whether there is a non-empty Tempo url in relation data."""
        return self._is_not_empty(self.tempo_url)

    @property
    def tls_ca_ready(self):
        """Check whether there is a TLS CA in relation data."""
        return self._is_not_empty(self.tls_ca)

    @property
    def prometheus_endpoint(self) -> dict:
        """Return the prometheus endpoint dict."""
        if not self.prometheus_ready:
            return {}

        endpoint = {}
        endpoint["url"] = self.prometheus_url
        if self.credentials:
            endpoint["basic_auth"] = {
                "username": self.credentials.username,
                "password": self.credentials.password,
            }
        return endpoint

    @property
    def loki_url(self) -> str:
        """The Loki endpoint from relation data."""
        return self._data.get("loki_url", "")

    @property
    def tempo_url(self) -> str:
        """The Tempo endpoint from relation data."""
        return self._data.get("tempo_url", "")

    @property
    def prometheus_url(self) -> str:
        """The Prometheus endpoint from relation data."""
        return self._data.get("prometheus_url", "")

    @property
    def tls_ca(self) -> str:
        """TLS CA from relation data."""
        return self._data.get("tls-ca", "")

    @property
    def _data(self):
        for relation in self._charm.model.relations[self._relation_name]:
            logger.info("%s %s %s", relation, self._relation_name, relation.data[relation.app])
            return relation.data[relation.app]
        return {}
