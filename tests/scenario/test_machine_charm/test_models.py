# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from typing import List

import pydantic
import pytest
from charms.grafana_agent.v0.cos_agent import CosAgentProviderUnitData, GrafanaDashboard


class Foo(pydantic.BaseModel):
    dash: List[GrafanaDashboard]


def test_dashboard_validation():
    raw_dash = {"totl": "foo", "bar": "baz"}
    with pytest.raises(pydantic.ValidationError):
        Foo(dash=[raw_dash])


def test_dashboard_serialization():
    raw_dash = {"title": "foo", "bar": "baz"}
    encoded_dashboard = GrafanaDashboard._serialize(json.dumps(raw_dash))
    data = Foo(dash=[encoded_dashboard])
    assert data.json() == '{"dash": ["{encoded_dashboard}"]}'.replace(
        "{encoded_dashboard}", encoded_dashboard
    )


def test_cos_agent_provider_unit_data_dashboard_serialization():
    raw_dash = {"title": "title", "foo": "bar"}
    encoded_dashboard = GrafanaDashboard()._serialize(json.dumps(raw_dash))
    data = CosAgentProviderUnitData(
        metrics_alert_rules={},
        log_alert_rules={},
        metrics_scrape_jobs=[],
        log_slots=[],
        dashboards=[encoded_dashboard],
    )
    assert json.loads(data.json()) == {
        "metrics_alert_rules": {},
        "log_alert_rules": {},
        "dashboards": [encoded_dashboard],
        "metrics_scrape_jobs": [],
        "log_slots": [],
    }


def test_dashboard_deserialization_roundtrip():
    raw_dash = {"title": "title", "foo": "bar"}
    encoded_dashboard = GrafanaDashboard()._serialize(json.dumps(raw_dash))
    raw = {
        "metrics_alert_rules": {},
        "log_alert_rules": {},
        "metrics_scrape_jobs": [],
        "log_slots": [],
        "dashboards": [encoded_dashboard],
    }
    data = CosAgentProviderUnitData(**raw)
    assert GrafanaDashboard(data.dashboards[0])._deserialize() == raw_dash
