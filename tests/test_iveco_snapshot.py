import json
from types import SimpleNamespace

from core import gateway, gateway_push, relay, servicenow, weather

INCIDENTS = dict(observed_at="2026-10-30 15:00", group="E_ITA_XXX_INNOVATION_REPORTING", open=1, stale=0,
                 by_state={"New": 1}, by_priority={"2 - High": 1},
                 items=[dict(number="INC0000001", state="New", priority="2 - High", assigned_to="",
                             short_description="x" * 500, age_days=3, days_since_update=None, extra="ignored")])


def test_desktop_snapshot_carries_incidents_only_when_present():
    assert "iveco_incidents" not in gateway_push.build_snapshot([], None)
    snapshot = gateway_push.build_snapshot([], INCIDENTS)
    assert snapshot["iveco_incidents"]["items"][0]["number"] == "INC0000001"


def test_vps_keeps_known_incident_fields_and_truncates(tmp_path):
    body = dict(feed=[], iveco_incidents=INCIDENTS)
    cleaned = gateway._clean_snapshot(body)["iveco_incidents"]
    item = cleaned["items"][0]
    assert "extra" not in item and len(item["short_description"]) == 300
    assert item["days_since_update"] == "" and item["age_days"] == "3"
    assert cleaned["open"] == 1 and cleaned["group"] == INCIDENTS["group"]


def test_vps_drops_malformed_incidents():
    assert "iveco_incidents" not in gateway._clean_snapshot(dict(feed=[], iveco_incidents={"items": "no"}))


def test_relay_answer_context_uses_snapshot_incidents(tmp_path, monkeypatch):
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps(dict(sent_at=1, feed=[], iveco_incidents=INCIDENTS)), encoding="utf-8")
    monkeypatch.setattr(gateway, "SNAPSHOT_FILE", snapshot_file)
    monkeypatch.setattr(weather, "set_device_location", lambda location: None)
    monkeypatch.setattr(weather, "get_weather_line", lambda: None)
    stub = SimpleNamespace(current_location=lambda: None)
    context = relay.Relay.context(stub, "ci sono incident aperti?")
    assert "INC0000001" in context and "dati dello snapshot del PC" in context


def test_relay_context_says_when_no_incident_data(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "SNAPSHOT_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(weather, "set_device_location", lambda location: None)
    monkeypatch.setattr(weather, "get_weather_line", lambda: None)
    stub = SimpleNamespace(current_location=lambda: None)
    assert "nessun dato dal PC" in relay.Relay.context(stub, "incident")


def test_chat_tool_incidents_action(monkeypatch):
    monkeypatch.setattr(servicenow, "incidents", lambda loop: dict(INCIDENTS, items=INCIDENTS["items"] * 50))
    monkeypatch.setattr(servicenow, "_browser_loop", lambda loop: "loop")
    result = servicenow.tool("incidents")
    assert result["open"] == 1 and len(result["items"]) == 40
