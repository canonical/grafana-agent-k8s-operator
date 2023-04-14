# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import MagicMock

import pytest
from charms.grafana_agent.v0.cos_agent import (
    CosAgentPeersUnitData,
    CosAgentProviderUnitData,
    COSAgentRequirer,
    GrafanaDashboard,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from ops.charm import CharmBase
from ops.framework import Framework
from scenario import PeerRelation, Relation, State, SubordinateRelation


def encode_as_dashboard(dct: dict):
    return GrafanaDashboard._serialize(json.dumps(dct).encode("utf-8"))


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
        "dashboards": [encode_as_dashboard(py_dash)],
    }
    relation.app = app
    relation.data = {unit: {CosAgentPeersUnitData.KEY: json.dumps(config)}, app: {}}

    obj = MagicMock()
    obj._charm.unit = unit

    obj.peer_relation = relation
    data = COSAgentRequirer._gather_peer_data(obj)
    assert len(data) == 1

    data_peer_1 = data[0]
    assert len(data_peer_1.dashboards) == 1
    dash_out_raw = data_peer_1.dashboards[0]
    assert GrafanaDashboard(dash_out_raw)._deserialize() == py_dash


class MyRequirerCharm(CharmBase):
    META = {
        "name": "test",
        "requires": {
            "cos-agent": {"interface": "cos_agent", "scope": "container"},
            "send-remote-write": {"interface": "prometheus_remote_write"},
        },
        "peers": {"peers": {"interface": "grafana_agent_replica"}},
    }

    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.cosagent = COSAgentRequirer(self)
        self.prom = PrometheusRemoteWriteConsumer(self)
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
    peer_relation = PeerRelation(endpoint="peers", interface="grafana_agent_replica")

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
    cos_agent = SubordinateRelation(
        endpoint="cos-agent", interface="cos_agent", primary_app_name="primary"
    )
    peer_relation = PeerRelation(endpoint="peers", interface="grafana_agent_replica")

    state = State(relations=[peer_relation, cos_agent])

    def post_event(charm: MyRequirerCharm):
        assert not charm.cosagent.dashboards

    state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event=cos_agent.changed_event(remote_unit_id=0),
        post_event=post_event,
    )


@pytest.mark.parametrize("leader", (True, False))
def test_cosagent_to_peer_data_flow_dashboards(leader):
    # This test verifies that if the charm receives via cos-agent a dashboard,
    # it is correctly transferred to peer relation data.

    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    raw_data_1 = CosAgentProviderUnitData(
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=[],
        dashboards=[encode_as_dashboard(raw_dashboard_1)],
    )
    cos_agent = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        primary_app_name="primary",
        remote_unit_data={raw_data_1.KEY: raw_data_1.json()},
    )
    peer_relation = PeerRelation(endpoint="peers", interface="grafana_agent_replica")

    state = State(relations=[peer_relation, cos_agent], leader=leader)

    def post_event(charm: MyRequirerCharm):
        assert charm.cosagent.dashboards

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        event=cos_agent.changed_event(remote_unit_id=0),
        post_event=post_event,
    )

    peer_relation_out = next(filter(lambda r: r.endpoint == "peers", state_out.relations))
    peer_data = peer_relation_out.local_unit_data[CosAgentPeersUnitData.KEY]
    assert json.loads(peer_data)["dashboards"] == [encode_as_dashboard(raw_dashboard_1)]


@pytest.mark.parametrize("leader", (True, False))
def test_cosagent_to_peer_data_flow_relation(leader):
    # dump the data the same way the provider would
    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    data_1 = CosAgentProviderUnitData(
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=[],
        dashboards=[encode_as_dashboard(raw_dashboard_1)],
    )

    cos_agent_1 = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        primary_app_name="primary",
        remote_unit_data={data_1.KEY: data_1.json()},
    )

    raw_dashboard_2 = {"title": "other_title", "foo": "other bar (would that be a pub?)"}
    data_2 = CosAgentProviderUnitData(
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=[],
        dashboards=[encode_as_dashboard(raw_dashboard_2)],
    )

    cos_agent_2 = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        primary_app_name="other_primary",
        remote_unit_data={data_2.KEY: data_2.json()},
    )

    # now the peer relation already contains the primary/0 information
    # i.e. we've already seen cos_agent_1-relation-changed before
    peer_relation = PeerRelation(
        endpoint="peers",
        interface="grafana_agent_replica",
        peers_data={
            1: {
                CosAgentPeersUnitData.KEY: CosAgentPeersUnitData(
                    principal_unit_name="principal",
                    principal_relation_id="42",
                    principal_relation_name="foobar-relation",
                    dashboards=[encode_as_dashboard(raw_dashboard_1)],
                ).json()
            }
        },
    )

    state = State(
        leader=leader,
        relations=[
            peer_relation,
            cos_agent_1,
            cos_agent_2,
        ],
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

        other_dash, dash = dashboards
        assert dash["title"] == "title"
        assert dash["content"] == raw_dashboard_1

        assert other_dash["title"] == "other_title"
        assert other_dash["content"] == raw_dashboard_2

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        # now it's the 2nd relation that's reporting a change:
        # the charm should update peer data
        # and in post_event the dashboard should be there.
        event=cos_agent_2.changed_event(remote_unit_id=0),
        pre_event=pre_event,
        post_event=post_event,
    )

    peer_relation_out: PeerRelation = next(
        filter(lambda r: r.endpoint == "peers", state_out.relations)
    )
    # the dashboard we just received via cos-agent is now in our local peer databag
    peer_data_local = peer_relation_out.local_unit_data[CosAgentPeersUnitData.KEY]
    assert json.loads(peer_data_local)["dashboards"] == [encode_as_dashboard(raw_dashboard_2)]

    # the dashboard we previously had via peer data is still there.
    peer_data_peer = peer_relation_out.peers_data[1][CosAgentPeersUnitData.KEY]
    assert json.loads(peer_data_peer)["dashboards"] == [encode_as_dashboard(raw_dashboard_1)]


@pytest.mark.parametrize("leader", (True, False))
def test_cosagent_to_peer_data_app_vs_unit(leader):
    # this test verifies that if multiple units (belonging to different apps) all publish their own
    # CosAgentProviderUnitData via `cos-agent`, then the `peers` peer relation will be populated
    # with the right data.
    # This means:
    # - The per-app data is only collected once per application (dedup'ed).
    # - The per-unit data is collected across all units.

    # dump the data the same way the provider would
    raw_dashboard_1 = {"title": "title", "foo": "bar"}
    data_1 = CosAgentProviderUnitData(
        dashboards=[encode_as_dashboard(raw_dashboard_1)],
        metrics_alert_rules={"a": "b", "c": 1},
        log_alert_rules={"a": "b", "c": 2},
        metrics_scrape_jobs=[{"1": 2, "2": 3}],
        log_slots=["foo:bar", "bax:qux"],
    )

    # there's an "other_primary" app also relating over `cos-agent`
    raw_dashboard_2 = {"title": "other_title", "foo": "other bar (would that be a pub?)"}
    data_2 = CosAgentProviderUnitData(
        dashboards=[encode_as_dashboard(raw_dashboard_2)],
        metrics_alert_rules={"a": "h", "c": 1},
        log_alert_rules={"a": "h", "d": 2},
        metrics_scrape_jobs=[{"1": 2, "4": 3}],
        log_slots=["dead:beef", "bax:quff"],
    )

    cos_agent_2 = SubordinateRelation(
        endpoint="cos-agent",
        interface="cos_agent",
        primary_app_name="other_primary",
        remote_unit_data={data_2.KEY: data_2.json()},
    )

    # suppose that this unit's primary is 'other_primary/0'.

    # now the peer relation already contains the primary/0 information
    # i.e. we've already seen cos_agent_1-relation-changed before
    peer_relation = PeerRelation(
        endpoint="peers",
        interface="grafana_agent_replica",
        # one of this unit's peers, who has as primary "primary/23", has already
        # logged its part of the data
        peers_data={
            1: {
                CosAgentPeersUnitData.KEY: CosAgentPeersUnitData(
                    principal_unit_name="primary/23",
                    principal_relation_id="42",
                    principal_relation_name="cos-agent",
                    # data coming from `primary` is here:
                    dashboards=data_1.dashboards,
                    metrics_alert_rules=data_1.metrics_alert_rules,
                    log_alert_rules=data_1.log_alert_rules,
                ).json()
            }
        },
    )

    state = State(
        leader=leader,
        relations=[
            peer_relation,
            cos_agent_2,
        ],
    )

    def pre_event(charm: MyRequirerCharm):
        # verify that before the event is processed, the charm correctly gathers only 1 dashboard
        dashboards = charm.cosagent.dashboards
        assert len(dashboards) == 1

        dash = dashboards[0]
        assert dash["title"] == "title"
        assert dash["content"] == raw_dashboard_1

    def post_event(charm: MyRequirerCharm):
        # after the event is processed, the charm has copied its primary's 'cos-agent' data into
        # its 'peers' peer databag, therefore there are now two dashboards.
        # The source of the dashboards is peer data.

        dashboards = charm.cosagent.dashboards
        assert len(dashboards) == 2

        dash = dashboards[0]
        assert dash["title"] == "other_title"
        assert dash["content"] == raw_dashboard_2

        dash = dashboards[1]
        assert dash["title"] == "title"
        assert dash["content"] == raw_dashboard_1

    state_out = state.trigger(
        charm_type=MyRequirerCharm,
        meta=MyRequirerCharm.META,
        # our primary #0 has just updated its peer relation databag
        event=cos_agent_2.changed_event(remote_unit_id=0),
        pre_event=pre_event,
        post_event=post_event,
    )

    peer_relation_out: PeerRelation = next(
        filter(lambda r: r.endpoint == "peers", state_out.relations)
    )
    my_databag_peer_data = peer_relation_out.local_unit_data[CosAgentPeersUnitData.KEY]
    assert set(json.loads(my_databag_peer_data)["dashboards"]) == {
        encode_as_dashboard(raw_dashboard_2)
    }

    peer_databag_peer_data = peer_relation_out.peers_data[1][CosAgentPeersUnitData.KEY]
    assert json.loads(peer_databag_peer_data)["dashboards"][0] == encode_as_dashboard(
        raw_dashboard_1
    )
