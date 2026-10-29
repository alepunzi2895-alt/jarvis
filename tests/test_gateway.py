import asyncio
import time

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from core import gateway as gateway_module
from core.gateway import Gateway
from core.live_server import LiveServer
from core.relay import Relay

PC_TOKEN = "gateway-secret"
RELAY_TOKEN = "relay-secret"
LOGIN = {"Tailscale-User-Login": "ale@example.com"}
SNAPSHOT = {"pc_time": "2026-10-30 09:00:00", "feed": [
    {"id": "1", "at": "2026-10-30 08:59:00", "source": "telegram", "prompt": "", "text": "meteo ok"},
    {"id": "2", "at": "2026-10-30 08:59:30", "source": "telegram_in", "prompt": "che tempo fa?", "text": ""},
]}


def make_relay(answered):
    async def answer(text, channel):
        answered.append((text, channel))
        return "risposta VPS"

    async def send(text):
        pass
    return Relay(RELAY_TOKEN, "watch-secret", "pc-secret", answer=answer, send=send)


async def make_client(tmp_path, answered=None, pc_url="http://127.0.0.1:9", user=""):
    answered = [] if answered is None else answered
    relay = make_relay(answered)
    app = web.Application(client_max_size=8 * 1024 * 1024)
    gateway = Gateway(relay, pc_live_url=pc_url, gateway_token=PC_TOKEN, gateway_user=user,
                      snapshot_file=tmp_path / "snapshot.json",
                      offline_page=gateway_module.OFFLINE_PAGE)
    gateway.attach(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, relay, gateway, answered


def test_snapshot_needs_relay_token_and_marks_pc_alive(tmp_path):
    async def run():
        client, relay, gateway, _ = await make_client(tmp_path)
        try:
            bad = await client.post("/pc/snapshot", json=SNAPSHOT, headers={"Authorization": "Bearer nope"})
            assert bad.status == 401
            good = await client.post("/pc/snapshot", json=SNAPSHOT, headers={"Authorization": f"Bearer {RELAY_TOKEN}"})
            assert good.status == 200
            assert relay.pc_alive()
            state = await (await client.get("/offline/state", headers=LOGIN)).json()
            assert state["pc_alive"] is True
            assert [item["id"] for item in state["snapshot"]["feed"]] == ["1", "2"]
        finally:
            await client.close()
    asyncio.run(run())


def test_offline_page_and_no_pc_services_when_pc_off(tmp_path):
    async def run():
        client, _, _, _ = await make_client(tmp_path)
        try:
            page = await client.get("/", headers=LOGIN)
            assert page.status == 200
            assert "PC spento" in await page.text()
            # Asset statici dalla VPS anche a PC spento; le API restano legate al PC: 503 leggibile.
            assert (await client.get("/live.js", headers=LOGIN)).status == 200
            assert (await client.post("/api/jarvis", json={"action": "tasks_recent"}, headers=LOGIN)).status == 503
        finally:
            await client.close()
    asyncio.run(run())


def test_strangers_outside_tailnet_are_refused(tmp_path):
    async def run():
        client, _, _, _ = await make_client(tmp_path, user="ale@example.com")
        try:
            assert (await client.get("/offline/state")).status == 403
            assert (await client.get("/offline/state", headers={"Tailscale-User-Login": "x@y.z"})).status == 403
        finally:
            await client.close()
    asyncio.run(run())


def test_offline_chat_answers_with_mobile_channel_and_refuses_when_pc_alive(tmp_path):
    async def run():
        answered = []
        client, relay, _, _ = await make_client(tmp_path, answered=answered)
        try:
            response = await client.post("/offline/ask", json={"text": "che tempo fa?"}, headers=LOGIN)
            assert (await response.json()) == {"ok": True, "reply": "risposta VPS"}
            assert answered == [("che tempo fa?", "mobile")]
            assert (await client.post("/offline/ask", json={"text": ""}, headers=LOGIN)).status == 400
            relay.pc_seen = time.monotonic()
            busy = await client.post("/offline/ask", json={"text": "ciao"}, headers=LOGIN)
            assert busy.status == 409
            assert answered == [("che tempo fa?", "mobile")]
        finally:
            await client.close()
    asyncio.run(run())


def test_pc_alive_proxies_http_with_gateway_headers_and_websocket(tmp_path):
    async def echo_headers(request):
        return web.json_response({
            "path": request.raw_path,
            "gateway": request.headers.get("X-Jarvis-Gateway"),
            "user": request.headers.get("X-Jarvis-User"),
            "origin": request.headers.get("Origin"),
            "tailscale": request.headers.get("Tailscale-User-Login"),
            "cookie": request.headers.get("Cookie"),
        })

    async def socket_echo(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                await ws.send_str("eco:" + message.data)
        return ws

    async def run():
        upstream_app = web.Application()
        upstream_app.router.add_get("/live/ws", socket_echo)
        upstream_app.router.add_route("*", "/{tail:.*}", echo_headers)
        upstream = TestServer(upstream_app)
        await upstream.start_server()
        pc_url = f"http://127.0.0.1:{upstream.port}"
        client, relay, _, _ = await make_client(tmp_path, pc_url=pc_url, user="ale@example.com")
        try:
            relay.pc_seen = time.monotonic()
            data = await (await client.get("/api/x?a=1", headers={**LOGIN, "Cookie": "jarvis_live=abc",
                                                                     "X-Jarvis-Gateway": "forged"})).json()
            assert data["path"] == "/api/x?a=1"
            assert data["gateway"] == PC_TOKEN
            assert data["user"] == "ale@example.com"
            assert data["origin"] == pc_url
            assert data["tailscale"] is None
            assert data["cookie"] == "jarvis_live=abc"

            socket = await client.ws_connect("/live/ws", headers=LOGIN)
            await socket.send_str("ciao")
            assert (await socket.receive_str()) == "eco:ciao"
            await socket.close()
        finally:
            await client.close()
            await upstream.close()
    asyncio.run(run())


def test_live_server_accepts_gateway_identity_only_with_token():
    server = LiveServer("pw", {"https://tl.example.ts.net:8443"}, engine=object(), gateway_token=PC_TOKEN)

    class Req:
        host = "tl.example.ts.net:8443"

        def __init__(self, headers):
            self.headers = headers

    proxied = Req({"X-Jarvis-Gateway": PC_TOKEN, "X-Jarvis-User": "Ale@Example.com"})
    assert server.tailscale_identity(proxied) == "ale@example.com"
    forged = Req({"X-Jarvis-Gateway": "wrong", "X-Jarvis-User": "ale@example.com"})
    assert server.tailscale_identity(forged) is None
    direct = Req({"Tailscale-User-Login": "ale@example.com"})
    assert server.tailscale_identity(direct) == "ale@example.com"


def test_static_assets_served_by_vps_without_touching_pc(tmp_path):
    # PC irraggiungibile di proposito: i file statici devono arrivare lo stesso.
    async def run():
        client, relay, _, _ = await make_client(tmp_path, pc_url="http://127.0.0.1:9", user="")
        try:
            relay.pc_seen = time.monotonic()
            for path in ("/live.js", "/app.js", "/style.css", "/orb.js"):
                response = await client.get(path, headers=LOGIN)
                assert response.status == 200, path
                assert (await response.read()) == (gateway_module.STATIC_DIR / path[1:]).read_bytes()
            video = await client.get("/media/online.mp4", headers={**LOGIN, "Range": "bytes=0-99"})
            assert video.status == 206
            assert len(await video.read()) == 100
            # Fuori dalla lista: niente file locali, va al PC (qui irraggiungibile).
            other = await client.get("/core/gateway.py", headers=LOGIN)
            assert other.status == 503
        finally:
            await client.close()
    asyncio.run(run())


def test_servicenow_reads_use_browser_loop_bound_at_startup():
    # Il tool ServiceNow della chat deve trovare il loop del browser anche prima di ogni lettura.
    from core import browser, servicenow
    loop = asyncio.new_event_loop()
    try:
        browser.get_agent().loop = loop
        assert servicenow._browser_loop(None) is loop
    finally:
        loop.close()
        browser._agent.loop = None
