# Contributing to grafana-agent-operator

## Overview

This documents explains the processes and practices recommended for
contributing enhancements to the Loki charm.

- Generally, before developing enhancements to this charm, you should consider opening an issue explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/lma) or [Discourse](https://discourse.charmhub.io/). The primary authors of this charm are available on the Mattermost channel as `@dylanstathis` and `@jose-masson`.
- It is strongly recommended that prior to engaging in any enhancements to this charm you familiarise your self with Juju.
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on PRs.
- All enhancements require review before being merged. Besides the code quality and test coverage, the review will also take into account the resulting user experience for Juju administrators using this charm. Please help us out in having easier reviews by rebasing onto the `main` branch, avoid merge commits and enjoy a linear Git history.


### Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments to a [microk8s](https://microk8s.io/) cluster can be done using the following commands

```bash
    sudo snap install microk8s --classic
    microk8s.enable dns storage
    sudo snap install juju --classic
    juju bootstrap microk8s microk8s
    juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath
```

### Developing + Testing

All tests can be executed by running `tox` without arguments.

To run individual test environments:

```bash
tox -e fmt  # Apply coding style standards to code
tox -e integration  # Run integration tests
tox -e lint  # Check your code complies to linting rules
tox -e static # Run static analysis
tox -e unit  # Run unit tests
```

Unit tests are implemented using the Operator Framework [test harness](https://ops.readthedocs.io/en/latest/#module-ops.testing).

### Build

Install the [charmcraft tool](https://juju.is/docs/sdk/setting-up-charmcraft) and build the charm in this git repository:

```bash
    tox -e render-k8s
    charmcraft pack
```

Deploy the charm with:

```bash
    juju deploy ./grafana-agent-k8s_ubuntu-20.04-amd64.charm --resource agent-image='ghcr.io/canonical/grafana-agent:latest'
```

## Code Overview

The core implementation of this charm is represented by the [`GrafanaAgentOperatorCharm`](src/charm.py) class.
`GrafanaAgentOperatorCharm` responds to the following events:

- `self.on.install`: In this event we patch K8s service ports.
- `self.on.agent_pebble_ready`: In this event the charm builds the Pebble layer to be added in the workload charm. This Pebble layer will manage the execution of Promtail binary
- `self.on["send-remote-write"].relation_changed`: In this event the Grafana agent config is updated with remote-write settings.
- `self._scrape.on.targets_changed`: In this event the Grafana agent config is updated with scrape settings.
- `self._loki_consumer.on.loki_push_api_endpoint_joined`: In this event the Grafana agent config is updated with Loki settings.
- `self._loki_consumer.on.loki_push_api_endpoint_departed`: In this event the Grafana agent config is updated with Loki settings.
