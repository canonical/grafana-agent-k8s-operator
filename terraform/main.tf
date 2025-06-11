resource "juju_application" "grafana_agent" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model              = var.model
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "grafana-agent-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
