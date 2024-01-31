output "grafana_application_name" {
  description = "Name of the deployed application."
  value       = juju_application.grafana-agent-k8s.name
}