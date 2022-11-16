#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""
import logging
import pathlib
from typing import Union

import yaml
from charms.grafana_agent_k8s.v0.grafana_agent import CONFIG_PATH, GrafanaAgentCharm
from ops.main import main

logger = logging.getLogger(__name__)


class GrafanaAgentK8sCharm(GrafanaAgentCharm):
    """K8s version of the Grafana Agent charm."""

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)
        self.framework.observe(self.on.agent_pebble_ready, self.on_pebble_ready)

    def on_pebble_ready(self, _) -> None:
        """Event handler for the pebble ready event.

        Args:
            event: The event object of the pebble ready event
        """
        self._container.push(CONFIG_PATH, yaml.dump(self._config_file()), make_dirs=True)

        pebble_layer = {
            "summary": "agent layer",
            "description": "pebble config layer for Grafana Agent",
            "services": {
                "agent": {
                    "override": "replace",
                    "summary": "agent",
                    "command": f"/bin/agent {self._cli_args()}",
                    "startup": "enabled",
                },
            },
        }
        self._container.add_layer(self._name, pebble_layer, combine=True)
        self._container.autostart()

        if (version := self._agent_version) is not None:
            self.unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: could not get Alertmanager version."
            )
        self._update_status()

    def is_ready(self):
        """Checks if the charm is ready for configuration."""
        return self._container.can_connect()

    def agent_version_output(self) -> str:
        """Runs `agent -version` and returns the output.

        Returns:
            Output of `agent -version`
        """
        version_output, _ = self._container.exec(["/bin/agent", "-version"]).wait_output()
        return version_output

    def read_file(self, filepath: Union[str, pathlib.Path]):
        """Read a file's contents.

        Returns:
            A string with the file's contents
        """
        return self._container.pull(filepath).read()

    def write_file(self, path: Union[str, pathlib.Path], text: str) -> None:
        """Write text to a file.

        Args:
            path: file path to write to
            text: text to write to the file
        """
        self._container.push(path, text)

    def restart(self) -> None:
        """Restart grafana agent."""
        self._container.restart("agent")


if __name__ == "__main__":
    main(GrafanaAgentK8sCharm)
