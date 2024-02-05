# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model_name" {
  description = "Name of Juju model to deploy application to"
  type        = string
  default     = ""
}

variable "app_name" {
  description = "Name of the application in the Juju model"
  type        = string
  default     = "grafana"
}

variable "channel" {
  description = "The channel to use when deploying a charm "
  type        = string
  default     = "latest/stable"
}

variable "grafana_config" {
  description = "Additional configurations for the Grafana. Please see the available options: https://charmhub.io/grafana-agent-k8s/configure"
  default     = {}
}
