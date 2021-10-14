# grafana-agent-operator

## Developing

To build and deploy the charm

    charmcraft build
    juju deploy ./grafana-agent-k8s_ubuntu-20.04-amd64.charm --resource agent-image='grafana/agent:v0.18.2'

## Testing

The Python operator framework includes a very nice harness for testing operator
behaviour without full deployment. These tests are run using tox:

    tox

To run the integration tests, use tox as well:

    tox -e integration
