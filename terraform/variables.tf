variable "model_name" {
  description = "Name of Juju model to deploy application to"
  type        = string
  default     = ""
}

variable "channel" {
  description = "The channel to use when deploying a charm "
  type        = string
  default     = "latest/stable"
}

variable "grafana-config" {
  description = "Additional configuration for the Grafana"
  default     = {}
}

variable "metrics_remote_write_offer_url" {
  description = "Prometheus offer URL for `send-remote-write` endpoint"
  type        = string
  default     = ""
}

variable "logging_offer_url" {
  description = "Loki offer URL for `logging-consumer` endpoint"
  type        = string
  default     = ""
}
