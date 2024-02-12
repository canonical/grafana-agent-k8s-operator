# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.grafana-agent-k8s.name
}

# Required integration endpoints

output "certificates_endpoint" {
  description = "Name of the endpoint to get the X.509 certificate using tls-certificates interface."
  value       = "certificates"
}

output "send_remote_write_endpoint" {
  description = "Name of the endpoint to forward client charms metrics and associated alert rules to Prometheus using prometheus_remote_write interface."
  value       = "send-remote-write"
}

output "metrics_endpoint" {
  description = "Name of the endpoint to expose the Prometheus metrics endpoint providing telemetry about the Grafana instance using prometheus_scrape interface."
  value       = "metrics-endpoint"
}

output "logging_consumer_endpoint" {
  description = "Name of the endpoint to send the logs to Loki using loki_push_api interface."
  value       = "logging-consumer"
}

output "grafana_dashboards_consumer_endpoint" {
  description = "Name of the endpoint to provide meaningful dashboards about it's metrics using grafana_dashboard interface."
  value       = "grafana-dashboards-consumer"
}

output "grafana_cloud_config_endpoint" {
  description = "Name of the endpoint to forward telemetry to any Prometheus(or Loki) compatible endpoint using grafana_cloud_config interface."
  value       = "grafana-cloud-config"
}

output "receive_ca_cert_endpoint" {
  description = "Name of the endpoint to get the Self signed X.509 Certificates through the relation with Self Signed Certificates Charm using certificate_transfer interface."
  value       = "receive-ca-cert"
}

# Provided integration endpoints

output "logging_provider_endpoint" {
  description = "Name of the endpoint provided by Grafana to receive logs from any charm that supports the loki_push_api relation interface."
  value       = "logging-provider"
}

output "grafana_dashboards_provider_endpoint" {
  description = "Name of the endpoint provided by Grafana to provide meaningful dashboards about its metrics to be shown in a Grafana Charm over the grafana-dashboard relation using the grafana-dashboard interface."
  value       = "grafana-dashboards-provider"
}
