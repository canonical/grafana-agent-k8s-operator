# Terraform module for grafana-agent-k8s

This is a Terraform module facilitating the deployment of grafana-agent-k8s charm, using the [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs).


## Requirements
This module requires a `juju` model to be available. Refer to the [usage section](#usage) below for more details.

## API

### Inputs
The module offers the following configurable inputs:

| Name | Type | Description | Default |
| - | - | - | - |
| `app_name`| string | Name to give the deployed application | grafana-agent |
| `channel`| string | Channel that the charm is deployed from |  |
| `config`| map(string) | Map of the charm configuration options | {} |
| `constraints`| string | Constraints for the Juju deployment|  |
| `model`| string | Reference to an existing model resource or data source for the model to deploy to |  |
| `revision`| number | Revision number of the charm |  |
| `storage_directives`| map(string) | Map of storage used by the application, which defaults to 1 GB, allocated by Juju. | {} |
| `units`| number | Unit count/scale | 1 |

### Outputs
Upon application, the module exports the following outputs:

| Name | Description |
| - | - |
| `app_name`|  Application name |
| `endpoints`|  Map of `requires` and `provides` endpoints |

## Usage

### Basic usage
