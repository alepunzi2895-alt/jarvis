import asyncio
import datetime as dt
import threading

import pytest

from core import outlook_web


def test_email_row_maps_sender_subject_time_and_preview():
    row = {"lines": ["ROSSI Mario", "Rilascio PRD", "10:42", "Ciao, il job e' andato"], "bold": True}
    email = outlook_web._email(row)
    assert email == dict(sender="ROSSI Mario", subject="Rilascio PRD", received="10:42", unread=True,
                         snippet="Ciao, il job e' andato")


def test_email_row_with_only_sender_and_subject():
    email = outlook_web._email({"lines": ["Bianchi", "Report"], "bold": False})
    assert (email["sender"], email["subject"], email["received"], email["unread"]) == ("Bianchi", "Report", "", False)


def test_parse_event_italian_label():
    day = dt.date(2026, 10, 27)
    event = outlook_web._parse_event(
        "Weekly sync, dalle 10:00 alle 10:30, martedì 27 ottobre 2026, Riunione di Microsoft Teams", day)
    assert event == dict(subject="Weekly sync", start="2026-10-27T10:00:00", end="2026-10-27T10:30:00", location="")


def test_parse_event_english_meridiem_and_dash():
    day = dt.date(2026, 10, 27)
    event = outlook_web._parse_event("Deploy review, 1:30 PM to 2:15 PM, Tuesday", day)
    assert (event["start"], event["end"]) == ("2026-10-27T13:30:00", "2026-10-27T14:15:00")
    event = outlook_web._parse_event("Stand-up, 09:15 - 09:30, Organizzatore X", day)
    assert (event["subject"], event["start"]) == ("Stand-up", "2026-10-27T09:15:00")


def test_parse_event_label_starting_with_time_takes_following_title():
    event = outlook_web._parse_event("10:00 - 11:00, Allineamento IVGAgent, Sala 3", dt.date(2026, 10, 27))
    assert event["subject"] == "Allineamento IVGAgent"


def test_parse_event_past_midnight_and_invalid():
    event = outlook_web._parse_event("Rilascio notturno, 23:30 - 00:30", dt.date(2026, 10, 27))
    assert event["end"] == "2026-10-28T00:30:00"
    assert outlook_web._parse_event("Nessun orario qui, tutto il giorno", dt.date(2026, 10, 27)) is None
    assert outlook_web._parse_event("Strano, 25:00 - 26:00", dt.date(2026, 10, 27)) is None


def test_run_caches_calendar_and_validates_params(monkeypatch):
    calls = []

    async def events(day):
        calls.append(day)
        return [{"subject": "A", "start": f"{day}T09:00:00", "end": f"{day}T10:00:00", "location": ""}]

    monkeypatch.setitem(outlook_web._ACTIONS, "events", events)

    async def scenario():
        first = await outlook_web.run("events", {"day": "2026-10-27"})
        second = await outlook_web.run("events", {"day": "2026-10-27"})
        assert first == second
        with pytest.raises(outlook_web.OutlookWebError):
            await outlook_web.run("events", {"day": "ieri"})
        with pytest.raises(outlook_web.OutlookWebError):
            await outlook_web.run("send", {})

    asyncio.run(scenario())
    assert calls == ["2026-10-27"]  # la seconda lettura arriva dalla cache


def test_run_expired_login_pauses_retries(monkeypatch):
    calls = []

    async def emails(count, unread_only):
        calls.append(count)
        raise PermissionError("login")

    monkeypatch.setitem(outlook_web._ACTIONS, "emails", emails)

    async def scenario():
        for _ in range(3):
            with pytest.raises(outlook_web.OutlookWebError, match="accesso Microsoft"):
                await outlook_web.run("emails", {"count": 5})

    asyncio.run(scenario())
    assert calls == [5]  # niente raffiche sulla pagina di login


def test_run_wraps_unexpected_errors(monkeypatch):
    async def unread():
        raise RuntimeError("selettore cambiato")

    monkeypatch.setitem(outlook_web._ACTIONS, "unread", unread)
    with pytest.raises(outlook_web.OutlookWebError, match="RuntimeError"):
        asyncio.run(outlook_web.run("unread", {}))


def test_call_sync_runs_on_bound_loop_from_another_thread(monkeypatch):
    async def unread():
        return 7

    monkeypatch.setitem(outlook_web._ACTIONS, "unread", unread)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        outlook_web.bind(loop)
        assert outlook_web.call_sync("unread") == 7

        async def from_the_loop():
            with pytest.raises(outlook_web.OutlookWebError, match="sincrona"):
                outlook_web.call_sync("unread")

        asyncio.run_coroutine_threadsafe(from_the_loop(), loop).result(5)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


def test_call_sync_without_livebridge_fails_fast():
    with pytest.raises(outlook_web.OutlookWebError, match="non configurato"):
        outlook_web.call_sync("unread")
