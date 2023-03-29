import base64
import json
import lzma
from unittest.mock import MagicMock

from ops.charm import CharmBase
from ops.framework import Framework
from scenario import State, Relation

from charms.grafana_agent.v0.cos_agent import COSAgentRequirer, COSAgentProvider


def test_fetch_data_from_relation():
    relation = MagicMock()
    unit = MagicMock()
    app = MagicMock()

    relation.units = [unit]
    content = json.dumps({"title": "title", "foo": "bar"})
    encoded_content = bytes(json.dumps(content), 'utf-8')
    compressed = COSAgentProvider._encode_dashboard_content(encoded_content)
    config = {"dashboards": {"dashboards": [compressed]}}
    relation.app = app
    relation.data = {
        app: {"config": json.dumps(config)},
        unit: {}
    }

    obj = MagicMock()
    obj._charm.unit = unit

    obj.peer_relation = relation
    COSAgentRequirer._gather_peer_data(obj, 'dashboards', 'dashboards')


class MyRequirerCharm(CharmBase):
    META = {
        'name': 'test',
        'requires': {'cos-agent': {'interface': 'cos_agent'}},
        'peers': {'cluster': {'interface': 'grafana_agent_replica'}}
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

    state.trigger(charm_type=MyRequirerCharm, meta=MyRequirerCharm.META, event='update-status',
                  post_event=post_event)


def test_no_dashboards_peer():
    peer_relation = Relation(endpoint='cluster', interface='grafana_agent_replica')

    state = State(relations=[peer_relation])

    def post_event(charm: MyRequirerCharm):
        assert not charm.cosagent.dashboards

    state.trigger(charm_type=MyRequirerCharm, meta=MyRequirerCharm.META, event='update-status',
                  post_event=post_event)


def test_no_dashboards_peer_cosagent():
    cos_agent = Relation(endpoint='cos-agent', interface='cos_agent', remote_app_name='primary')
    peer_relation = Relation(endpoint='cluster', interface='grafana_agent_replica')

    state = State(relations=[peer_relation, cos_agent])

    def post_event(charm: MyRequirerCharm):
        assert not charm.cosagent.dashboards

    state.trigger(charm_type=MyRequirerCharm,
                  meta=MyRequirerCharm.META,
                  event=cos_agent.changed_event(remote_unit=0),
                  post_event=post_event)


def test_cosagent_to_peer_data_flow_dashboards():
    raw_content_1 = {"title": "title", "foo": "bar"}
    encoded_content_1 = bytes(json.dumps(raw_content_1), 'utf-8')
    compressed_1 = COSAgentProvider._encode_dashboard_content(encoded_content_1)
    config_1 = {"dashboards": {"dashboards": [compressed_1]}}

    databag_contents_1 = {'config': json.dumps(config_1)}

    cos_agent = Relation(
        endpoint='cos-agent', interface='cos_agent',
        remote_app_name='primary',
        remote_app_data=databag_contents_1,
        remote_units_data={0: databag_contents_1}
    )
    peer_relation = Relation(endpoint='cluster', interface='grafana_agent_replica')

    state = State(
        relations=[
            peer_relation,
            cos_agent]
    )

    def post_event(charm: MyRequirerCharm):
        assert charm.cosagent.dashboards

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event=cos_agent.changed_event(remote_unit=0),
        post_event=post_event)

    peer_relation_out = next(filter(lambda r: r.endpoint == 'cluster', state_out.relations))
    assert peer_relation_out.local_unit_data['primary/0'] == json.dumps(databag_contents_1)


def test_cosagent_to_peer_data_flow():
    raw_content_1 = {"title": "title", "foo": "bar"}
    encoded_content_1 = bytes(json.dumps(raw_content_1), 'utf-8')
    compressed_1 = COSAgentProvider._encode_dashboard_content(encoded_content_1)
    config_1 = {"dashboards": {"dashboards": [compressed_1]}}

    databag_contents_1 = {'config': json.dumps(config_1)}

    cos_agent_1 = Relation(
        endpoint='cos-agent', interface='cos_agent',
        remote_app_name='primary',
        remote_app_data=databag_contents_1,
        remote_units_data={0: databag_contents_1}
    )

    raw_content_2 = {"title": "other_title", "foo": "other bar (would that be a pub?)"}
    encoded_content_2 = bytes(json.dumps(raw_content_2), 'utf-8')
    compressed_2 = COSAgentProvider._encode_dashboard_content(encoded_content_2)
    config_2 = {"dashboards": {"dashboards": [compressed_2]}}

    databag_contents_2 = {'config': json.dumps(config_2)}

    cos_agent_2 = Relation(
        endpoint='cos-agent', interface='cos_agent',
        remote_app_name='other_primary',
        remote_app_data=databag_contents_2,
        remote_units_data={0: databag_contents_2}
    )
    peer_relation = Relation(endpoint='cluster', interface='grafana_agent_replica')

    state = State(
        relations=[
            peer_relation,
            cos_agent_1,
            cos_agent_2,
        ]
    )

    def post_event(charm: MyRequirerCharm):
        dashboards = charm.cosagent.dashboards
        assert dashboards

        assert len(dashboards) == 1

        dash = dashboards[0]
        assert dash['title'] == 'title'
        assert json.loads(dash['content']) == raw_content_1

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event=cos_agent_1.changed_event(remote_unit=0),
        post_event=post_event)

    peer_relation_out = next(filter(lambda r: r.endpoint == 'cluster', state_out.relations))
    assert peer_relation_out.local_unit_data['primary/0'] == json.dumps(databag_contents_1)


def test_cosagent_to_peer_data_flow_rel_2():
    raw_content_1 = {"title": "title", "foo": "bar"}
    encoded_content_1 = bytes(json.dumps(raw_content_1), 'utf-8')
    compressed_1 = COSAgentProvider._encode_dashboard_content(encoded_content_1)
    config_1 = {"dashboards": {"dashboards": [compressed_1]}}

    databag_contents_1 = {'config': json.dumps(config_1)}

    cos_agent_1 = Relation(
        endpoint='cos-agent', interface='cos_agent',
        remote_app_name='primary',
        remote_app_data=databag_contents_1,
        remote_units_data={0: databag_contents_1}
    )

    raw_content_2 = {"title": "other_title", "foo": "other bar (would that be a pub?)"}
    encoded_content_2 = bytes(json.dumps(raw_content_2), 'utf-8')
    compressed_2 = COSAgentProvider._encode_dashboard_content(encoded_content_2)
    config_2 = {"dashboards": {"dashboards": [compressed_2]}}

    databag_contents_2 = {'config': json.dumps(config_2)}

    cos_agent_2 = Relation(
        endpoint='cos-agent', interface='cos_agent',
        remote_app_name='other_primary',
        remote_app_data=databag_contents_2,
        remote_units_data={0: databag_contents_2}
    )

    # now the peer relation already contains the primary/0 information
    # i.e. we've already seen cos_agent_1-relation-changed before
    peer_relation = Relation(
        endpoint='cluster',
        interface='grafana_agent_replica',
        local_unit_data={'primary/0': json.dumps(databag_contents_1)})

    state = State(
        relations=[
            peer_relation,
            cos_agent_1,
            cos_agent_2,
        ]
    )

    def post_event(charm: MyRequirerCharm):
        dashboards = charm.cosagent.dashboards
        assert dashboards

        dash = dashboards[0]
        assert dash['title'] == 'title'
        assert json.loads(dash['content']) == raw_content_1

        dash = dashboards[1]
        assert dash['title'] == 'other_title'
        assert json.loads(dash['content']) == raw_content_2

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        # now it's the 2nd relation that's reporting a change:
        # the charm should update peer data
        # and in post_event the dashboard should be there.
        event=cos_agent_2.changed_event(remote_unit=0),
        post_event=post_event)

    peer_relation_out = next(filter(lambda r: r.endpoint == 'cluster', state_out.relations))
    assert peer_relation_out.local_unit_data['primary/0'] == json.dumps(databag_contents_1)
    assert peer_relation_out.local_unit_data['other_primary/0'] == json.dumps(databag_contents_2)
