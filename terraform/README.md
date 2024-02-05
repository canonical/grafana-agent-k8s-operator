# Grafana-agent-k8s Terraform Module

This Grafana-agent-k8s Terraform module aims to deploy the [grafana-agent-k8s charm](https://charmhub.io/grafana-agent-k8s) via Terraform.

## Getting Started

### Prerequisites

The following software and tools needs to be installed and should be running in the local environment. Please [set up your environment](https://discourse.charmhub.io/t/set-up-your-development-environment-with-microk8s-for-juju-terraform-provider/13109) before deployment.

- `microk8s`
- `juju 3.x`
- `terrafom`

### Module structure

- **main.tf** - Defines the Juju application to be deployed.
- **variables.tf** - Allows customization of the deployment. Except for exposing the deployment options (Juju model name, channel or application name) also models the charm configuration.
- **output.tf** - Responsible for integrating the module with other Terraform modules, primarily by defining potential integration endpoints (charm integrations), but also by exposing the application name.
- **terraform.tf** - Defines the Terraform provider.

## Using Grafana-agent-k8s base module in higher level modules

If you want to use `grafana-agent-k8s` base module as part of your Terraform module, import it like shown below.

```text
module "grafana-agent-k8s" {
  source = "git::https://github.com/canonical/grafana-agent-k8s-operator//terraform"
  
  model_name = "juju_model_name"
  # Optional Configurations
  # channel                        = "put the Charm channel here" 
  # grafana-config = {
  #   tls_insecure_skip_verify = "put True not to skip the TLS verification"
  # }
}
```

Please see the link to customize the Grafana configuration variables if needed.

- [Grafana configuration option](https://charmhub.io/grafana-agent-k8s/configure)

Create the integrations, for instance:

```text
resource "juju_integration" "amf-metrics" {
  model = var.model_name

  application {
    name     = module.amf.app_name
    endpoint = module.grafana.metrics_endpoint
  }

  application {
    name     = module.grafana.app_name
    endpoint = module.grafana.metrics_endpoint
  }
}
```

Please check the available [integration pairs](https://charmhub.io/grafana-agent-k8s/integrations).

[Terraform](https://www.terraform.io/)

[Terraform Juju provider](https://registry.terraform.io/providers/juju/juju/latest)
