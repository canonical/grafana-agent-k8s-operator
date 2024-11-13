resource "juju_application" "grafana_agent" {
  name  = var.app_name
  model = var.model_name
  trust = true
  charm {
    name     = "grafana-agent-k8s"
    channel  = var.channel
    revision = var.revision
  }
  units  = var.units
  config = var.config
}
