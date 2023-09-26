# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json

from charm import GrafanaAgentK8sCharm
from cosl import GrafanaDashboard
from scenario import Container, Context, Relation, State


def encode_as_dashboard(dct: dict):
    return GrafanaDashboard._serialize(json.dumps(dct).encode("utf-8"))


class TestDashboardPropagation:
    """TestDashboardPropagation checks that dashboard propagation works in the K8s charm."""

    def test_dashboard_propagation(self, vroot):
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
            relation_id=1,
            remote_app_data={"dashboards": json.dumps(data)},
        )

        provider = Relation("grafana-dashboards-provider", relation_id=2)

        ctx = Context(charm_type=GrafanaAgentK8sCharm, charm_root=vroot)
        state = State(
            relations=[consumer, provider],
            leader=True,
            containers=[Container("agent", can_connect=True)],
        )

        def post_event(charm):
            dash = charm.dashboards[0]
            assert dash["charm"] == expected["charm"]
            assert dash["title"] == expected["title"]
            assert dash["content"] == expected["content"]._deserialize()

        ctx.run(
            state=state,
            event=consumer.changed_event,
            post_event=post_event,
        )
