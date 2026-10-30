from datetime import datetime, timedelta, timezone

from core import servicenow


def _row(number, state="Work in Progress", priority="2 - High", assigned="Mario Rossi", age=10, quiet=2):
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    stamp = lambda days: (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return dict(number=number, state=state, priority=priority, assigned_to=assigned,
                opened_at=stamp(age), updated_at=stamp(quiet), short_description=f"{number} desc")


def test_incident_list_url_matches_manual_view():
    assert "incident_list.do%3Fsysparm_query%3Dactive%253Dtrue%255Euniversal_requestISEMPTY%255E" \
           f"assignment_group.nameSTARTSWITH{servicenow.GROUP}%26sysparm_first_row%3D1" in servicenow.INCIDENT_LIST_URL


def test_incident_stats_sorts_by_priority_then_age_and_counts_stale():
    rows = [_row("INC0000002", priority="3 - Moderate", age=5, quiet=1),
            _row("INC0000001", priority="1 - Critical", age=2, quiet=40),
            _row("INC0000003", priority="1 - Critical", age=9, quiet=3, assigned="")]
    now = datetime(2026, 10, 30, 12, 0)
    stats = servicenow.incident_stats(rows, now)
    assert stats["open"] == 3
    assert [i["number"] for i in stats["items"]] == ["INC0000003", "INC0000001", "INC0000002"]
    assert stats["stale"] == 1
    assert stats["by_priority"] == {"1 - Critical": 2, "3 - Moderate": 1}
    assert stats["items"][0]["assigned_to"] == "non assegnato"


def test_read_incidents_uses_browser_with_incident_query(monkeypatch):
    calls = []

    def fake_read(loop, url, script, args):
        calls.append((loop, url, script, args))
        return [_row("INC0000001")]

    monkeypatch.setattr(servicenow, "_read_on_browser", fake_read)
    stats = servicenow.incidents("loop-x")
    assert stats["open"] == 1
    loop, url, script, args = calls[0]
    assert loop == "loop-x" and url == servicenow.INCIDENT_LIST_URL
    assert "/api/now/table/incident?" in script and "universal_requestISEMPTY" in script
    assert args == {"group": servicenow.GROUP}
