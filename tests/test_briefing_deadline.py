import threading
import time

from core import briefing


def test_slow_source_is_left_out_after_deadline(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(briefing.weather, "get_weather_line", lambda: "sole")
    monkeypatch.setattr(briefing.outlook, "get_upcoming_events_sync", lambda minutes_ahead: release.wait(5) or [])
    monkeypatch.setattr(briefing.outlook, "count_unread_emails_sync", lambda: 3)
    monkeypatch.setattr(briefing.project_status, "check_all", lambda executor: [])
    monkeypatch.setattr(briefing.myfxbook, "ENABLED", False)
    started = time.monotonic()
    data = briefing.gather_briefing_data(object(), deadline=0.3)
    release.set()
    assert time.monotonic() - started < 1
    assert data["weather"] == "sole" and data["unread"] == 3 and data["events"] is None
