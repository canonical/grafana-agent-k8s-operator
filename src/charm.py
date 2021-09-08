#!/usr/bin/env python3

#  Copyright 2021 Canonical Ltd.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging

import yaml
from ops.charm import CharmBase
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)


class GrafanaAgentOperatorCharm(CharmBase):
    """Grafana Agent Charm"""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.agent_pebble_ready, self.on_pebble_ready)

    def on_pebble_ready(self, event: EventBase) -> None:
        """Event handler for the pebble ready event

        Args:
            event: The event object of the pebble ready event
        """
        container = event.workload
        container.push("/etc/agent/agent.yaml", self._config_file())
        pebble_layer = {
            "summary": "agent layer",
            "description": "pebble config layer for Grafana Agent",
            "services": {
                "agent": {
                    "override": "replace",
                    "summary": "agent",
                    "command": f"/bin/agent {self._cli_args()}",
                    "startup": "enabled",
                }
            },
        }
        container.add_layer("agent", pebble_layer, combine=True)
        container.autostart()
        self.unit.status = ActiveStatus()

    def _cli_args(self) -> str:
        """Return the cli arguments to pass to agent

        Returns:
            The arguments as a string
        """
        return "-config.file=/etc/agent/agent.yaml -prometheus.wal-directory=/tmp/agent/data"

    def _config_file(self) -> str:
        """Put all the config sections together and return the main config file

        Returns:
            The config file contents
        """
        config = {}
        if server_config := self._server_config():
            config["server"] = server_config
        if integrations_config := self._integrations_config():
            config["integrations"] = integrations_config
        if prometheus_config := self._prometheus_config():
            config["prometheus"] = prometheus_config
        if loki_config := self._loki_config():
            config["loki"] = loki_config
        return yaml.dump(config)

    def _server_config(self) -> dict:
        """Return the server section of the config

        Returns:
            The dict representing the config
        """
        return {"log_level": "info"}

    def _integrations_config(self) -> dict:
        """Return the integrations section of the config

        Returns:
            The dict representing the config
        """
        return {"agent": {"enabled": True}}

    def _prometheus_config(self) -> dict:
        """Return the prometheus section of the config

        Returns:
            The dict representing the config
        """
        return {}

    def _loki_config(self) -> dict:
        """Return the loki section of the config

        Returns:
            The dict representing the config
        """
        return {}


if __name__ == "__main__":
    main(GrafanaAgentOperatorCharm)
