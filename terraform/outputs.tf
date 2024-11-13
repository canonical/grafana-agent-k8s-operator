output "app_name" {
  value = juju_application.grafana_agent.name
}

output "requires" {
  value = {
    certificates                = "certificates",
    send_remote_write           = "send-remote-write",
    metrics_endpoint            = "metrics-endpoint",
    logging_consumer            = "logging-consumer",
    grafana_dashboards_consumer = "grafana-dashboards-consumer",
    grafana_cloud_config        = "grafana-cloud-config",
    receive_ca_cert             = "receive-ca-cert",
    tracing                     = "tracing",
  }
}

output "provides" {
  value = {
    tracing_provider            = "tracing-provider",
    logging_provider            = "logging-provider",
    grafana_dashboards_provider = "grafana-dashboards-provider",
  }
}
