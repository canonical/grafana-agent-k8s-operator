# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json

from cosl import GrafanaDashboard
from ops.testing import Container, Context, Relation, State

from charm import GrafanaAgentK8sCharm


def encode_as_dashboard(dct: dict):
    return GrafanaDashboard._serialize(json.dumps(dct).encode("utf-8"))


def test_dashboard_propagation(ctx):
    # This test verifies that if the charm receives a dashboard via the requirer databag,
    # it is correctly transferred to the provider databag.

    content_in = encode_as_dashboard({"hello": "world"})
    expected = {
        "charm": "some-test-charm",
        "title": "file:some-mock-dashboard",
        "content": content_in,
    }
    data = {
        "templates": {
            "file:some-mock-dashboard": {"charm": "some-test-charm", "content": content_in}
        }
    }
    consumer = Relation(
        "grafana-dashboards-consumer",
        remote_app_data={"dashboards": json.dumps(data)},
    )

    provider = Relation("grafana-dashboards-provider")

    state = State(
        relations=[consumer, provider],
        leader=True,
        containers=[Container("agent", can_connect=True)],
    )

    with ctx(ctx.on.relation_changed(consumer), state=state) as mgr:
        dash = mgr.charm.dashboards[0]
        assert dash["charm"] == expected["charm"]
        assert dash["title"] == expected["title"]
        assert dash["content"] == expected["content"]._deserialize()
