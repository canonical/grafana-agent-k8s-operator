# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import pytest
from ops.testing import Container, Context, Relation, State

import charm


@pytest.mark.parametrize("forwarding", (True, False))
def test_forward_alert_rules(forwarding):
    # GIVEN these relations
    prometheus_relation = Relation("send-remote-write", remote_app_name="prometheus")
    state = State(
        leader=True,
        containers={Container(name="agent", can_connect=True)},
        relations=[
            prometheus_relation,
        ],
        config={"forward_alert_rules": forwarding},
    )
    # WHEN the charm receives a config-changed event
    ctx = Context(
        charm_type=charm.GrafanaAgentK8sCharm,
    )
    with ctx(ctx.on.config_changed(), state) as mgr:
        output_state = mgr.run()
        # THEN the charm is forwarding the alerts
        prometheus_relation_out = output_state.get_relation(prometheus_relation.id)
        if forwarding:
            assert prometheus_relation_out.local_app_data["alert_rules"] != "{}"
        else:
            assert prometheus_relation_out.local_app_data["alert_rules"] == "{}"
