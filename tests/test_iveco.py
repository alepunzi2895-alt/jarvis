import asyncio
from datetime import datetime
import json
import threading

import pytest

from core import iveco


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 10, 19, 9, 30), datetime(2026, 10, 16)),  # lunedi' -> venerdi'
    (datetime(2026, 10, 16, 9, 30), datetime(2026, 10, 15)),  # venerdi' -> giovedi'
    (datetime(2026, 10, 18, 12, 0), datetime(2026, 10, 16)),  # domenica -> venerdi'
])
def test_window_starts_on_previous_working_day(now, expected):
    assert iveco.window_start(now) == expected


def test_next_recap_skips_weekend_and_past_times(monkeypatch):
    monkeypatch.setattr(iveco, "RECAP_TIME", "09:30")
    assert iveco.next_recap_at(datetime(2026, 10, 16, 8, 0)) == datetime(2026, 10, 16, 9, 30)
    assert iveco.next_recap_at(datetime(2026, 10, 16, 9, 30)) == datetime(2026, 10, 19, 9, 30)
    assert iveco.next_recap_at(datetime(2026, 10, 17, 7, 0)) == datetime(2026, 10, 19, 9, 30)


def test_gather_survives_every_source_failing(monkeypatch):
    def broken(*args):
        raise RuntimeError("giu'")
    for name in ("_job_runs", "_workspace_changes", "_dashboard_changes", "_apps", "_deploys", "_mail", "_meetings"):
        monkeypatch.setattr(iveco, name, broken)
    data = iveco.gather(datetime(2026, 10, 16, 9, 30))
    assert data["since"] == "2026-10-15 00:00"
    assert data["facts"] == {}
    assert data["sources"]["mail"] == "non disponibile (RuntimeError)"
    assert data["sources"]["teams"] == "non disponibile (RuntimeError)"  # nessun loop browser


def test_build_recap_saves_summary_and_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(iveco, "RECAP_FILE", tmp_path / ".iveco-recap.json")
    monkeypatch.setattr(iveco, "gather", lambda now=None, loop=None: dict(now="2026-10-16 09:30", since="2026-10-15 00:00",
                                                               facts={"mail": []}, sources={"mail": "ok"}))
    monkeypatch.setattr(iveco, "summarize", lambda data: "Fatto: nulla di rilevante")
    record = iveco.build_recap()
    assert record["text"] == "Fatto: nulla di rilevante"
    assert iveco.latest() == record
    assert json.loads((tmp_path / ".iveco-recap.json").read_text(encoding="utf-8"))["since"] == "2026-10-15 00:00"


def test_iso_after_handles_utc_and_bad_values():
    since = datetime(2026, 10, 15)
    assert iveco._iso_after("2026-10-16T08:00:00Z", since)
    assert not iveco._iso_after("2026-10-01T08:00:00Z", since)
    assert not iveco._iso_after(None, since)
    assert not iveco._iso_after("ieri", since)


def test_teams_reads_chat_list_on_browser_loop(monkeypatch):
    from core import browser
    rossi = dict(id="19:a", kind="OneGQL_OneOnOneChatConversation", title="ROSSI Mario",
                 preview="puoi guardare il job?", at="2026-10-16T07:10:00Z", unread=True)

    class Agent:
        async def read_teams_chats(self, url):
            assert url == iveco.TEAMS_URL
            return [
                rossi,
                dict(rossi),  # stessa chat anche tra i Preferiti
                dict(id="48:notes", kind="OneGQL_SelfChatConversation", title="PUNZI (You)",
                     preview="VPS password", at="2026-10-16T08:00:00Z", unread=False),
                dict(id="19:b", kind="OneGQL_GroupChatConversation", title="Vecchia",
                     preview="x", at="2026-10-01T08:00:00Z", unread=False),
            ]

    monkeypatch.setattr(browser, "get_agent", lambda: Agent())
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        rows = iveco._teams(datetime(2026, 10, 15), loop)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()
    assert [row["chat"] for row in rows] == ["ROSSI Mario"]
    assert rows[0]["type"] == "1:1" and rows[0]["unread"]
    assert rows[0]["last_message"] == "puoi guardare il job?"


def test_recap_loop_sends_due_recap_with_browser_loop(monkeypatch):
    clock = iter([datetime(2026, 10, 16, 9, 0), datetime(2026, 10, 16, 9, 31)])
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(clock)
    sent, loops = [], []
    def build(now=None, loop=None):
        loops.append(loop)
        return {"text": "Fatto: deploy"}
    async def no_wait(seconds):
        if len(sent):
            raise asyncio.CancelledError
    monkeypatch.setattr(iveco, "datetime", Clock)
    monkeypatch.setattr(iveco, "RECAP_TIME", "09:30")
    monkeypatch.setattr(iveco, "build_recap", build)
    monkeypatch.setattr(iveco.asyncio, "sleep", no_wait)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(iveco.recap_loop(sent.append))
    assert sent == ["Recap per il daily delle 10:00\n\nFatto: deploy"]
    assert loops[0] is not None  # Teams si legge sul loop di LiveBridge
