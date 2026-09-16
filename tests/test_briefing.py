import datetime as dt

from core import briefing, outlook


def test_safe_returns_none_on_exception():
    def boom():
        raise RuntimeError("nope")

    assert briefing._safe(boom) is None


def test_safe_returns_value_on_success():
    assert briefing._safe(lambda: 42) == 42


def test_minutes_until_midnight_is_positive_and_capped_to_today():
    now = dt.datetime(2026, 9, 16, 23, 58, 0)
    assert briefing._minutes_until_midnight(now) >= 1
    assert briefing._minutes_until_midnight(now) <= 2


def test_gather_briefing_data_degrades_when_everything_fails(monkeypatch):
    monkeypatch.setattr(briefing.weather, "get_weather_line", lambda: (_ for _ in ()).throw(RuntimeError("net")))
    monkeypatch.setattr(briefing.outlook, "get_upcoming_events_sync", lambda **k: (_ for _ in ()).throw(outlook.OutlookError("no")))
    monkeypatch.setattr(briefing.outlook, "count_unread_emails_sync", lambda: (_ for _ in ()).throw(outlook.OutlookError("no")))
    monkeypatch.setattr(briefing.project_status, "check_all", lambda executor: (_ for _ in ()).throw(RuntimeError("git")))
    monkeypatch.setattr(briefing.myfxbook, "ENABLED", False)

    data = briefing.gather_briefing_data(executor=None)

    assert data["weather"] is None
    assert data["events"] is None
    assert data["unread"] is None
    assert data["statuses"] is None
    assert "trading" not in data


def test_format_briefing_text_includes_available_sections():
    now = dt.datetime(2026, 9, 16, 8, 0, 0)
    event = outlook.CalendarEvent(subject="Standup", start=now.replace(hour=9), end=now.replace(hour=9, minute=30), location="", entry_id="1")
    data = {"now": now, "weather": "22°C, sereno", "events": [event], "unread": 3, "statuses": None}

    text = briefing.format_briefing(data, voice=False)

    assert "Buongiorno" in text
    assert "22°C" in text
    assert "Standup" in text
    assert "3 mail non lette" in text


def test_format_briefing_voice_is_a_single_flowing_sentence():
    now = dt.datetime(2026, 9, 16, 8, 0, 0)
    data = {"now": now, "weather": "22°C, sereno", "events": [], "unread": 0, "statuses": None}

    text = briefing.format_briefing(data, voice=True)

    assert "\n" not in text
    assert "Signore" in text


def test_format_briefing_includes_trading_section_when_present():
    now = dt.datetime(2026, 9, 16, 8, 0, 0)
    account = briefing.myfxbook.AccountSnapshot(
        name="MFKK", balance=10000, equity=10500, gain=5, drawdown=2, profit=500, won_trades=7, lost_trades=3
    )
    data = {"now": now, "weather": None, "events": None, "unread": None, "statuses": None, "trading": [account]}

    text = briefing.format_briefing(data, voice=False)

    assert "MFKK" in text
