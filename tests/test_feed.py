import asyncio
from unittest.mock import MagicMock

from core import feed, telegram


def test_feed_keeps_order_strips_html_and_filters_after():
    feed.add("telegram", "<b>Recap</b> &amp; job", parse="HTML")
    feed.add("telegram_in", prompt="stato progetti")
    feed.add("telegram", "")  # vuoto: ignorato
    first, second = feed.recent()
    assert first["text"] == "Recap & job" and first["source"] == "telegram"
    assert second["prompt"] == "stato progetti" and second["text"] == ""
    assert feed.recent(first["id"]) == [second]
    assert feed.recent(second["id"]) == []


def test_feed_skips_half_written_lines():
    feed.add("voce", "ok", prompt="ciao")
    with feed.FEED.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "1')
    assert [item["text"] for item in feed.recent()] == ["ok"]


def test_send_to_owner_writes_feed_unless_disabled(monkeypatch):
    monkeypatch.setattr(telegram.requests, "post", MagicMock())
    telegram.send_to_owner("avviso job fallito")
    telegram.send_to_owner("risposta dashboard", feed=False)
    assert [item["text"] for item in feed.recent()] == ["avviso job fallito"]


def test_tasks_recent_merges_feed_with_session_chat():
    from tests.test_live_server import client_for, login

    async def scenario():
        client, server = await client_for()
        async with client:
            await login(client)
            feed.add("telegram_in", prompt="da telefono")
            [session] = server.sessions.values()
            session["history"].append(dict(id="r1", prompt="dalla dashboard", status="done", result="ok",
                                           at="2000-01-01 00:00:00"))
            tasks = (await (await client.post("/api/jarvis", json={"action": "tasks_recent"})).json())["tasks"]
            assert [(t.get("kind"), t["prompt"]) for t in tasks] == [("feed", "da telefono"), (None, "dalla dashboard")]
    asyncio.run(scenario())


def test_dashboard_reply_goes_to_telegram_without_feed_echo(monkeypatch):
    from tests.test_live_server import client_for, login, until
    sent = []
    monkeypatch.setattr(telegram, "send_to_owner", lambda *args: sent.append(args))

    async def scenario():
        client, _ = await client_for()
        async with client:
            await login(client)
            socket = await client.ws_connect("/live/ws")
            await until(socket, "ready")
            await socket.send_json(dict(type="text", id="one", prompt="ciao"))
            await until(socket, "done", "one")
            await socket.close()
    asyncio.run(scenario())
    [(text, parse, to_feed)] = sent
    assert text.startswith('\U0001F4BB "ciao"') and parse is None and to_feed is False
    assert feed.recent() == []
