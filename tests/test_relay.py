import asyncio
import time

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from core import relay as relay_module
from core.relay import Relay


def message_update(update_id, text="ciao", chat="42"):
    return {"update_id": update_id, "message": {"chat": {"id": int(chat)}, "text": text}}


def make_relay(monkeypatch, **kwargs):
    monkeypatch.setattr(relay_module, "OWNER_ID", "42")
    sent, answered = [], []

    async def send(text):
        sent.append(text)

    async def answer(text, channel):
        answered.append((text, channel))
        return "risposta VPS"
    relay = Relay("relay-secret", "watch-secret", "pc-secret", answer=answer, send=send, **kwargs)
    return relay, sent, answered


async def client_for(relay):
    app = web.Application()
    app.router.add_get("/telegram/updates", relay.updates)
    app.router.add_post("/watch/ask", relay.watch)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def test_pc_offline_vps_answers_and_ignores_strangers(monkeypatch):
    relay, sent, answered = make_relay(monkeypatch)
    async def run():
        await relay.dispatch(message_update(1, "che tempo fa?"))
        await relay.dispatch(message_update(2, "spam", chat="7"))
        await relay.dispatch(message_update(3, "/confirm abc"))
        await relay.dispatch({"update_id": 4, "message": {"chat": {"id": 42}, "voice": {}}})
    asyncio.run(run())
    assert answered == [("che tempo fa?", "telegram")]
    assert sent[0] == "☁️ risposta VPS"
    assert "comandi" in sent[1] and "testo" in sent[2]
    assert len(sent) == 3


def test_pc_online_gets_updates_in_telegram_format_and_vps_stays_silent(monkeypatch):
    relay, sent, answered = make_relay(monkeypatch)
    async def run():
        client = await client_for(relay)
        async with client:
            auth = {"Authorization": "Bearer relay-secret"}
            assert (await client.get("/telegram/updates", headers={"Authorization": "Bearer no"})).status == 401
            poll = asyncio.create_task(client.get("/telegram/updates?offset=0&timeout=5", headers=auth))
            await asyncio.sleep(0.2)
            assert relay.pc_alive()
            await relay.dispatch(message_update(10, "leggi la posta"))
            data = await (await poll).json()
            assert data == {"ok": True, "result": [message_update(10, "leggi la posta")]}
            await relay.fallback_if_unclaimed(10, grace=0)
            # Ack con offset successivo: l'update sparisce dal ponte.
            data = await (await client.get("/telegram/updates?offset=11&timeout=0", headers=auth)).json()
            assert data["result"] == [] and not relay.pending
    asyncio.run(run())
    assert answered == [] and sent == []


def test_unclaimed_update_falls_back_to_vps(monkeypatch):
    relay, sent, answered = make_relay(monkeypatch)
    relay.pc_seen = time.monotonic()  # PC visto da poco ma non piu' in ascolto
    async def run():
        await relay.dispatch(message_update(5, "stato tradepilot"))
        await relay.fallback_if_unclaimed(5, grace=0)
    asyncio.run(run())
    assert answered == [("stato tradepilot", "telegram")] and sent == ["☁️ risposta VPS"]


def test_watch_forwards_to_pc_when_alive_else_answers_locally(monkeypatch):
    relay, _, answered = make_relay(monkeypatch)
    calls = []

    async def pc_watch(request):
        calls.append((request.headers["Authorization"], (await request.json())["text"]))
        return web.Response(text="risposta PC")
    async def run():
        pc = TestClient(TestServer(web.Application()))
        pc.app.router.add_post("/watch/ask", pc_watch)
        await pc.start_server()
        monkeypatch.setattr(relay_module, "PC_WATCH_URL", str(pc.make_url("/watch/ask")))
        client = await client_for(relay)
        from aiohttp import ClientSession
        relay.session = ClientSession()
        async with client, pc:
            auth = {"Authorization": "Bearer watch-secret"}
            assert (await client.post("/watch/ask", json={"text": "x"})).status == 401
            relay.pc_seen = time.monotonic()
            assert await (await client.post("/watch/ask", json={"text": "agenda"}, headers=auth)).text() == "risposta PC"
            relay.pc_seen = 0
            assert await (await client.post("/watch/ask", json={"text": "meteo"}, headers=auth)).text() == "risposta VPS"
        await relay.session.close()
    asyncio.run(run())
    assert calls == [("Bearer pc-secret", "agenda")]
    assert answered == [("meteo", "watch")]


def test_watch_falls_back_when_pc_bridge_is_down(monkeypatch):
    relay, _, answered = make_relay(monkeypatch)
    monkeypatch.setattr(relay_module, "PC_WATCH_URL", "http://127.0.0.1:9/watch/ask")
    async def run():
        from aiohttp import ClientSession
        relay.session = ClientSession()
        client = await client_for(relay)
        async with client:
            relay.pc_seen = time.monotonic()
            response = await client.post("/watch/ask", json={"text": "ciao"}, headers={"Authorization": "Bearer watch-secret"})
            assert await response.text() == "risposta VPS"
        await relay.session.close()
    asyncio.run(run())
    assert answered == [("ciao", "watch")]


def test_relay_imports_stay_light():
    import subprocess, sys
    code = ("import sys; import core.relay; heavy = [m for m in ('cv2', 'faster_whisper', 'playwright', "
            "'sounddevice', 'core.claude_bridge') if m in sys.modules]; print(heavy)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=relay_module.ROOT)
    assert out.stdout.strip() == "[]", out.stderr


def test_watch_location_beats_pc_and_is_forwarded(monkeypatch, tmp_path):
    from core import weather
    monkeypatch.setattr(relay_module, "LOCATION_FILE", tmp_path / "loc.json")
    relay, _, _ = make_relay(monkeypatch)
    relay.remember_location("pc", "45.07", "7.69", "Torino")
    assert relay.current_location() == (45.07, 7.69, "Torino")
    relay.remember_location("watch", "38,9067", "1.4206", "Ibiza")
    assert relay.current_location() == (38.9067, 1.4206, "Ibiza")
    assert Relay("a", "b").locations["watch"][0] == (38.9067, 1.4206, "Ibiza")  # sopravvive al riavvio
    relay.locations["watch"] = (relay.locations["watch"][0], time.time() - 13 * 3600)
    assert relay.current_location()[2] == "Torino"
    relay.remember_location("watch", "999", "1", "x")  # coordinate impossibili: ignorate
    assert relay.locations["watch"][0][2] == "Ibiza"
    weather.set_device_location(None)


def test_pc_poll_and_watch_body_update_locations(monkeypatch, tmp_path):
    monkeypatch.setattr(relay_module, "LOCATION_FILE", tmp_path / "loc.json")
    relay, _, _ = make_relay(monkeypatch)
    received = []

    async def pc_watch(request):
        received.append(await request.json())
        return web.Response(text="ok")
    async def run():
        pc = TestClient(TestServer(web.Application()))
        pc.app.router.add_post("/watch/ask", pc_watch)
        await pc.start_server()
        monkeypatch.setattr(relay_module, "PC_WATCH_URL", str(pc.make_url("/watch/ask")))
        client = await client_for(relay)
        from aiohttp import ClientSession
        relay.session = ClientSession()
        async with client, pc:
            await client.get("/telegram/updates?offset=0&timeout=0&lat=45.07&lon=7.69&city=Torino",
                             headers={"Authorization": "Bearer relay-secret"})
            assert relay.locations["pc"][0] == (45.07, 7.69, "Torino")
            await client.post("/watch/ask", json={"text": "meteo", "lat": 38.9, "lon": 1.42, "city": "Ibiza"},
                              headers={"Authorization": "Bearer watch-secret"})
        await relay.session.close()
    asyncio.run(run())
    assert received == [{"text": "meteo", "lat": 38.9, "lon": 1.42, "city": "Ibiza"}]
    assert relay.current_location() == (38.9, 1.42, "Ibiza")


def test_weather_prefers_fresh_device_location(monkeypatch):
    from core import weather
    monkeypatch.setenv("JARVIS_WEATHER_LAT", "45.07")
    monkeypatch.setenv("JARVIS_WEATHER_LON", "7.69")
    weather.set_device_location((38.9, 1.42, "Ibiza"))
    assert weather._resolve_location() == (38.9, 1.42, "Ibiza")
    assert weather.base_location()[:2] == (45.07, 7.69)
    weather._device["at"] -= weather.DEVICE_LOCATION_SECONDS + 1
    assert weather._resolve_location()[:2] == (45.07, 7.69)
    weather._device.update(location=None, at=0.0)
