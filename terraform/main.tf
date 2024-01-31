resource "juju_application" "grafana-agent-k8s" {
  name  = "grafana-agent-k8s"
  model = var.model_name

  charm {
    name    = "grafana-agent-k8s"
    channel = var.channel
    base    = "ubuntu@22.04"
  }
  config = var.grafana-config
  units  = 1
  trust  = true
}

resource "juju_integration" "prometheus-remote-write" {
  count = var.metrics_remote_write_offer_url != "" ? 1 : 0
  model = var.model_name

  application {
    name     = juju_application.grafana-agent-k8s.name
    endpoint = "send-remote-write"
  }

  application {
    offer_url = var.metrics_remote_write_offer_url
  }
}

resource "juju_integration" "loki-logging" {
  count = var.logging_offer_url != "" ? 1 : 0
  model = var.model_name

  application {
    name     = juju_application.grafana-agent-k8s.name
    endpoint = "logging-consumer"
  }

  application {
    offer_url = var.logging_offer_url
  }
}

