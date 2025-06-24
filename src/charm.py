#!/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A  juju charm for Grafana Agent on Kubernetes."""

import copy
import json
import logging
import pathlib
from typing import Any, Dict, List, Union, cast

import yaml
from charms.loki_k8s.v1.loki_push_api import LokiPushApiProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from cosl import LZMABase64
from ops.main import main
from ops.pebble import Layer

from grafana_agent import CONFIG_PATH, GrafanaAgentCharm

logger = logging.getLogger(__name__)

SCRAPE_RELATION_NAME = "metrics-endpoint"


def key_value_pair_string_to_dict(key_value_pair: str) -> dict:
    """Transform a comma-separated key-value pairs into a dict."""
    result = {}

    for pair in key_value_pair.split(","):
        pair = pair.strip()
        if not pair:
            continue

        if ":" in pair:
            sep = ":"
        elif "=" in pair:
            sep = "="
        else:
            logger.error("Invalid pair without separator ':' or '=': '%s'", pair)
            continue

        key, value = map(str.strip, pair.split(sep, 1))

        if not key:
            logger.error("Empty key in pair: '%s'", pair)
            continue
        if not value:
            logger.error("Empty value in pair: '%s'", pair)
            continue

        result[key] = value

    return result

def inject_extra_labels_to_alert_rules(rules: dict, extra_alert_labels: dict) -> dict:
    """Inject extra alert labels into alert labels."""
    """Return a copy of the rules dict with extra labels injected."""
    result = copy.deepcopy(rules)
    for item in result.values():
        for group in item.get("groups", []):
            for rule in group.get("rules", []):
                rule.setdefault("labels", {}).update(extra_alert_labels)
    return result


@trace_charm(
    # implemented in GrafanaAgentCharm
    tracing_endpoint="_tracing_endpoint",
    server_cert="_server_ca_cert_path",
    extra_types=(
        GrafanaAgentCharm,
        LokiPushApiProvider,
        MetricsEndpointConsumer,
        LZMABase64,
    ),
)
class GrafanaAgentK8sCharm(GrafanaAgentCharm):
    """K8s version of the Grafana Agent charm."""

    mandatory_relation_pairs = {
        "metrics-endpoint": [  # must be paired with:
            {"send-remote-write"},  # or
            {"grafana-cloud-config"},
        ],
        "logging-provider": [  # must be paired with:
            {"logging-consumer"},  # or
            {"grafana-cloud-config"},
        ],
        "tracing-provider": [  # must be paired with:
            {"tracing"},  # or
            {"grafana-cloud-config"},
        ],
        "grafana-dashboards-consumer": [  # must be paired with:
            {"grafana-dashboards-provider"},  # or
            {"grafana-cloud-config"},
        ],
    }

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)
        self.unit.set_ports(self._http_listen_port, self._grpc_listen_port)
        self._forward_alert_rules = self.config["forward_alert_rules"]

        self._scrape = MetricsEndpointConsumer(self)
        self._loki_provider = LokiPushApiProvider(
            self, relation_name="logging-provider", port=self._http_listen_port
        )
        self.framework.observe(
            self._loki_provider.on.loki_push_api_alert_rules_changed,  # pyright: ignore
            self._on_loki_push_api_alert_rules_changed,
        )
        self.framework.observe(
            self._scrape.on.targets_changed,  # pyright: ignore
            self.on_scrape_targets_changed,
        )
        self.framework.observe(
            self.on["grafana-dashboards-consumer"].relation_changed,
            self._on_dashboards_changed,
        )
        self.framework.observe(
            self.on["grafana-dashboards-consumer"].relation_broken,
            self._on_dashboards_changed,
        )
        self.framework.observe(
            self.on.agent_pebble_ready,  # pyright: ignore
            self._on_agent_pebble_ready,
        )

    def _on_loki_push_api_alert_rules_changed(self, _event):
        """Refresh Loki alert rules."""
        self._update_loki_alerts()

    def _layer(self) -> Layer:
        """Generate the pebble layer."""
        return Layer(
            {
                "summary": "agent layer",
                "description": "pebble config layer for Grafana Agent",
                "services": {
                    self._name: {
                        "override": "replace",
                        "summary": "agent",
                        "command": self._command(),
                        "startup": "enabled",
                    },
                },
            },
        )

    def _command(self) -> str:
        return f"/bin/agent {self._cli_args()}"

    def is_command_changed(self) -> bool:
        """Compare the current command we'd issue with the one in the pebble layer."""
        if svc := self._container.get_plan().services.get(self._name):
            return svc.command != self._command()
        return True

    def _on_dashboards_changed(self, _event) -> None:
        logger.info("updating dashboards")

        if not self.unit.is_leader():
            return

        self.update_dashboards(
            dashboards=self.dashboards,
            reload_func=self._grafana_dashboards_provider._update_all_dashboards_from_dir,
            mapping=self.dashboard_paths,
        )

    def _on_agent_pebble_ready(self, _event) -> None:
        self._container.push(CONFIG_PATH, yaml.dump(self._generate_config()), make_dirs=True)

        self._container.add_layer(self._name, self._layer(), combine=True)
        self._container.autostart()

        if (version := self._agent_version) is not None:
            self.unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: could not get grafana-agent version."
            )
        self._update_status()

    def metrics_rules(self) -> Dict[str, Any]:
        """Return a list of metrics rules."""
        if not self._forward_alert_rules:
            return {}

        alert_rules = self._scrape.alerts
        extra_alert_labels = key_value_pair_string_to_dict(cast(str, self.model.config.get("extra_alert_labels", "")))

        if extra_alert_labels:
            alert_rules = inject_extra_labels_to_alert_rules(alert_rules, extra_alert_labels)

        return alert_rules


    @property
    def dashboards(self) -> list:
        """Returns an aggregate of all dashboards received by this grafana-agent."""
        aggregate = {}
        for rel in self.model.relations["grafana-dashboards-consumer"]:
            dashboards = json.loads(rel.data[rel.app].get("dashboards", "{}"))  # type: ignore
            if "templates" not in dashboards:
                continue
            for template in dashboards["templates"]:
                content = json.loads(
                    LZMABase64.decompress(dashboards["templates"][template].get("content"))
                )
                entry = {
                    "charm": dashboards["templates"][template].get("charm", "charm_name"),
                    "relation_id": rel.id,
                    "title": template,
                    "content": content,
                }
                aggregate[template] = entry

        return list(aggregate.values())

    def metrics_jobs(self) -> list:
        """Return a list of metrics scrape jobs."""
        return self._scrape.jobs()

    def logs_rules(self) -> Dict[str, Any]:
        """Return a list of logging rules."""
        return self._loki_provider.alerts if self._forward_alert_rules else {}

    @property
    def is_ready(self):
        """Checks if the charm is ready for configuration."""
        return self._container.can_connect()

    @property
    def _additional_integrations(self) -> Dict:
        """No additions for k8s charms."""
        return {}

    @property
    def _additional_log_configs(self) -> List[Dict[str, Any]]:
        """Additional per-type integrations to inject."""
        return []

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
        self._container.push(path, text, make_dirs=True)

    def delete_file(self, path: Union[str, pathlib.Path]):
        """Delete a file.

        Args:
            path: file to be deleted
        """
        self._container.remove_path(path)

    def stop(self) -> None:
        """Stop grafana agent."""
        self._container.stop("agent")

    def restart(self) -> None:
        """Restart grafana agent."""
        self._container.add_layer(self._name, self._layer(), combine=True)
        self._container.autostart()
        self._container.restart("agent")

    def positions_dir(self) -> str:
        """Return the positions directory."""
        return "/run"

    def run(self, cmd: List[str]):
        """Run cmd on the workload.

        Args:
            cmd: Command to be run.
        """
        self._container.exec(cmd).wait()


if __name__ == "__main__":
    main(GrafanaAgentK8sCharm)
