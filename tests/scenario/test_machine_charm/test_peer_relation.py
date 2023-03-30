import json
from unittest.mock import MagicMock

from charms.grafana_agent.v0.cos_agent import COSAgentProvider, COSAgentRequirer, CosAgentProviderUnitData, \
    GrafanaDashboard, CosAgentClusterUnitData
from ops.charm import CharmBase
from ops.framework import Framework
from scenario import Relation, State


def encode_as_dashboard(dct: dict):
    return GrafanaDashboard.serialize(json.dumps(dct).encode('utf-8'))


def test_fetch_data_from_relation():
    relation = MagicMock()
    unit = MagicMock()
    app = MagicMock()
    py_dash = {"title": "title", "foo": "bar"}

    relation.units = []  # there should be remote units in here, presumably
    config = {
        "principal_unit_name": "principal/0",
        "principal_relation_id": "0",
        "principal_relation_name": "foo",
        "dashboards": [encode_as_dashboard(py_dash)]
    }
    relation.app = app
    relation.data = {
        unit: {CosAgentClusterUnitData.VERSION: json.dumps(config)},
        app: {}
    }

    obj = MagicMock()
    obj._charm.unit = unit

    obj.peer_relation = relation
    data = COSAgentRequirer._gather_peer_data(obj)
    assert len(data) == 1

    data_peer_1 = data[0]
    assert len(data_peer_1.dashboards) == 1
    dash_out_raw = data_peer_1.dashboards[0]
    assert GrafanaDashboard(dash_out_raw).deserialize() == py_dash


class MyRequirerCharm(CharmBase):
    META = {
        "name": "test",
        "requires": {"cos-agent": {"interface": "cos_agent"}},
        "peers": {"cluster": {"interface": "grafana_agent_replica"}},
    }

    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.cosagent = COSAgentRequirer(self)
        framework.observe(self.cosagent.on.data_changed, self._on_cosagent_data_changed)

    def _on_cosagent_data_changed(self, _):
        pass


def test_no_dashboards():
    state = State()

    def post_event(charm: MyRequirerCharm):
        assert not charm.cosagent.dashboards

    state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event="update-status",
        post_event=post_event,
    )


def test_no_dashboards_peer():
    peer_relation = Relation(endpoint="cluster", interface="grafana_agent_replica")

    state = State(relations=[peer_relation])

    def post_event(charm: MyRequirerCharm):
        assert not charm.cosagent.dashboards

    state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event="update-status",
        post_event=post_event,
    )


def test_no_dashboards_peer_cosagent():
    cos_agent = Relation(endpoint="cos-agent", interface="cos_agent", remote_app_name="primary")
    peer_relation = Relation(endpoint="cluster", interface="grafana_agent_replica")

    state = State(relations=[peer_relation, cos_agent])

    def post_event(charm: MyRequirerCharm):
        assert not charm.cosagent.dashboards

    state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event=cos_agent.changed_event(remote_unit=0),
        post_event=post_event,
    )


def test_cosagent_to_peer_data_flow_dashboards():
    # This test verifies that if the charm receives via cos-agent a dashboard,
    # it is correctly transferred to peer relation data.

    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    raw_data_1 = CosAgentProviderUnitData(dashboards=[encode_as_dashboard(raw_dashboard_1)])
    cos_agent = Relation(
        endpoint="cos-agent",
        interface="cos_agent",
        remote_app_name="primary",
        remote_units_data={0: json.loads(raw_data_1.json())},
    )
    peer_relation = Relation(endpoint="cluster", interface="grafana_agent_replica")

    state = State(relations=[peer_relation, cos_agent])

    def post_event(charm: MyRequirerCharm):
        assert charm.cosagent.dashboards

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event=cos_agent.changed_event(remote_unit=0),
        post_event=post_event,
    )

    peer_relation_out = next(filter(lambda r: r.endpoint == "cluster", state_out.relations))
    peer_data = peer_relation_out.local_unit_data["v1"]
    assert json.loads(peer_data)['dashboards'] == [
            encode_as_dashboard(raw_dashboard_1)
        ]


def test_cosagent_to_peer_data_flow_relation():
    # dump the data the same way the provider would
    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    data_1 = CosAgentProviderUnitData(dashboards=[encode_as_dashboard(raw_dashboard_1)])
    cos_agent_1 = Relation(
        endpoint="cos-agent",
        interface="cos_agent",
        remote_app_name="primary",
        remote_units_data={0: json.loads(data_1.json())},
    )

    raw_dashboard_2 = {"title": "other_title", "foo": "other bar (would that be a pub?)"}
    data_2 = CosAgentProviderUnitData(dashboards=[encode_as_dashboard(raw_dashboard_2)])

    cos_agent_2 = Relation(
        endpoint="cos-agent",
        interface="cos_agent",
        remote_app_name="other_primary",
        remote_units_data={0: json.loads(data_2.json())},
    )

    # now the peer relation already contains the primary/0 information
    # i.e. we've already seen cos_agent_1-relation-changed before
    peer_relation = Relation(
        endpoint="cluster",
        interface="grafana_agent_replica",
        local_unit_data={
            CosAgentClusterUnitData.VERSION: CosAgentClusterUnitData(
                principal_unit_name='principal',
                principal_relation_id='42',
                principal_relation_name='foobar-relation',
                dashboards=[encode_as_dashboard(raw_dashboard_1)]).json()
        }
    )

    state = State(
        relations=[
            peer_relation,
            cos_agent_1,
            cos_agent_2,
        ]
    )

    def pre_event(charm: MyRequirerCharm):
        dashboards = charm.cosagent.dashboards
        assert len(dashboards) == 1

        dash = dashboards[0]
        assert dash["title"] == "title"
        assert dash["content"] == raw_dashboard_1

    def post_event(charm: MyRequirerCharm):
        dashboards = charm.cosagent.dashboards
        assert len(dashboards) == 2

        dash = dashboards[0]
        assert dash["title"] == "title"
        assert dash["content"] == raw_dashboard_1

        dash = dashboards[1]
        assert dash["title"] == "other_title"
        assert dash["content"] == raw_dashboard_2

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        # now it's the 2nd relation that's reporting a change:
        # the charm should update peer data
        # and in post_event the dashboard should be there.
        event=cos_agent_2.changed_event(remote_unit=0),
        pre_event=pre_event,
        post_event=post_event,
    )

    peer_relation_out = next(filter(lambda r: r.endpoint == "cluster", state_out.relations))
    peer_data = peer_relation_out.local_unit_data["v1"]
    assert set(json.loads(peer_data)['dashboards']) == {
            encode_as_dashboard(raw_dashboard_1),
            encode_as_dashboard(raw_dashboard_2)
        }
