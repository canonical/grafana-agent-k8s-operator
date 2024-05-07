# Grafana Agent Charmed Operator for Kubernetes 

[![Charmhub Badge](https://charmhub.io/grafana-agent-k8s/badge.svg)](https://charmhub.io/grafana-agent-k8s)
[![Release Edge](https://github.com/canonical/grafana-agent-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/grafana-agent-k8s-operator/actions/workflows/release.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

> #### ⚠️ Are you looking for the Grafana Agent _machine_ charm?
>
> The charms have been split into separate repositories. The machine charm is now available [here](https://github.com/canonical/grafana-agent-operator/).

## Description

[Grafana Agent](https://github.com/grafana/agent) is a telemetry collector for sending metrics,
logs, and trace data to the opinionated Grafana observability stack.

The Grafana Agent Charmed Operator deploys Grafana Agent in Kubernetes using [Juju](https://juju.is)
and the [Charmed Operator Lifecycle Manager (OLM)](https://juju.is/docs/olm).

As a single entry point to the [Canonical Observability Stack](https://charmhub.io/cos-lite), the Grafana Agent charm
brings several conveniences when deployed inside a monitored cluster:

- Charms are related to the Grafana Agent charm, instead of to Prometheus and
  Loki individually. In typical deployments this would reduce the number of
  cross-model relations that would have been otherwise needed.
- Conversion from scraping to remote writing: Grafana Agent would collect
  telemetry inside the cluster network and _push_ it to the COS cluster (via
  `loki_push_api` and `prometheus_remote_write`), which simplifies firewall
  configuration, as only outgoing connections would need to be established.

See [deployment scenarios](https://github.com/canonical/grafana-agent-k8s-operator/blob/main/INTEGRATING.md#deployment-scenarios)
for further detail.

## Usage

Create a Juju model for your operators, say "cos"

```bash
juju add-model cos
```

The Grafana agent may be deployed using the juju command line:

```bash
juju deploy grafana-agent-k8s --trust
```

If required, you can remove the deployment completely:

```bash
juju destroy-model -y cos --no-wait --force --destroy-storage
```

## Relations

Currently supported relations are:

```yaml
requires:
  send-remote-write:
    interface: prometheus_remote_write
  metrics-endpoint:
    interface: prometheus_scrape
  logging-consumer:
    interface: loki_push_api

provides:
  self-metrics-endpoint:
    interface: prometheus_scrape
  grafana-dashboard:
    interface: grafana_dashboard
  logging-provider:
    interface: loki_push_api
```

More detailed information about these relations can be found in [Charmhub docs page](https://charmhub.io/grafana-agent-k8s/docs/relations).


## OCI Images

This charm by default uses the `latest` release of the [grafana-agent](http://ghcr.io/canonical/grafana-agent)
