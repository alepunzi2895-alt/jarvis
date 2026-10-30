"""Gateway mobile sulla VPS: il telefono apre sempre la VPS.

PC acceso: la VPS fa da proxy verso il LiveBridge del PC (HTTP e websocket),
con tutti i servizi. PC spento: la VPS mostra l'ultimo snapshot del desktop
(inviato dal PC ogni ~30 s) e risponde alla chat di testo con le funzioni
leggere (Claude, meteo, TradePilot, second brain). Niente Iveco e niente voce
a PC spento: la VPS non ha ne' Iveco ne' whisper.

Il PC accetta il proxy solo con JARVIS_GATEWAY_TOKEN (intestazione
X-Jarvis-Gateway) e l'identita' Tailscale inoltrata in X-Jarvis-User.
"""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import time

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
from multidict import CIMultiDict

ROOT = Path(__file__).resolve().parents[1]
PC_LIVE_URL = os.getenv("JARVIS_PC_LIVE_URL", "").rstrip("/")
GATEWAY_TOKEN = os.getenv("JARVIS_GATEWAY_TOKEN", "")
GATEWAY_USER = os.getenv("JARVIS_GATEWAY_USER", "").strip().casefold()
SNAPSHOT_FILE = ROOT / ".relay-snapshot.json"
OFFLINE_PAGE = ROOT / "web/public/offline.html"
STATIC_DIR = ROOT / "web/public"
# Asset statici serviti dalla VPS stessa: niente giro verso il PC (2026-10-29: ~0,2 s a richiesta
# piu' il relay del telefono, il video da 1,6 MB arrivava dopo ~8 s). La VPS deve avere lo
# stesso web/public del PC: dopo ogni merge su main, aggiornare la VPS.
LOCAL_STATIC = {"/style.css", "/app.js", "/live.js", "/orb.js", "/media/online.mp4"}
SNAPSHOT_MAX_ITEMS = 60
SNAPSHOT_MAX_INCIDENTS = 60
INCIDENT_KEYS = ("number", "state", "priority", "assigned_to", "short_description", "age_days", "days_since_update")
SNAPSHOT_MAX_BYTES = 400_000
MAX_FRAME = 4 * 1024 * 1024
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
              "transfer-encoding", "upgrade", "content-length", "content-encoding", "host", "origin",
              "cookie", "tailscale-user-login", "x-jarvis-gateway", "x-jarvis-user"}
OFFLINE_CHAT = "mobile"


def _json(body, status=200):
    return web.json_response(body, status=status)


def _clean_snapshot(body):
    """Tiene solo campi noti e limiti di dimensione: lo snapshot arriva da un altro processo."""
    if not isinstance(body, dict) or not isinstance(body.get("feed"), list):
        raise ValueError("snapshot non valido")
    feed = []
    for item in body["feed"][-SNAPSHOT_MAX_ITEMS:]:
        if isinstance(item, dict):
            feed.append({key: str(item.get(key, ""))[:4000] for key in ("id", "at", "source", "prompt", "text")})
    snapshot = {"sent_at": time.time(), "pc_time": str(body.get("pc_time", ""))[:40], "feed": feed}
    incidents = _clean_incidents(body.get("iveco_incidents"))
    if incidents:
        snapshot["iveco_incidents"] = incidents
    if len(json.dumps(snapshot, ensure_ascii=False)) > SNAPSHOT_MAX_BYTES:
        snapshot["feed"] = feed[-10:]
    return snapshot


def _clean_incidents(body):
    """Incident letti dal PC (core/servicenow.py): solo campi noti, testi corti, max 60 righe."""
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        return None
    items = [{key: "" if item.get(key) is None else str(item.get(key))[:300] for key in INCIDENT_KEYS}
             for item in body["items"][:SNAPSHOT_MAX_INCIDENTS] if isinstance(item, dict)]
    return {"observed_at": str(body.get("observed_at", ""))[:40], "group": str(body.get("group", ""))[:120],
            "open": int(body.get("open") or 0), "stale": int(body.get("stale") or 0), "items": items}


class Gateway:
    def __init__(self, relay, pc_live_url=PC_LIVE_URL, gateway_token=GATEWAY_TOKEN,
                 gateway_user=GATEWAY_USER, snapshot_file=SNAPSHOT_FILE, offline_page=OFFLINE_PAGE):
        self.relay = relay
        self.pc_live_url = pc_live_url.rstrip("/")
        self.gateway_token = gateway_token
        self.gateway_user = gateway_user
        self.snapshot_file = Path(snapshot_file)
        self.offline_page = Path(offline_page)
        self.session = None

    # ── accesso ─────────────────────────────────────────────────────────
    def identity(self, request):
        """Solo tailnet: Tailscale Serve aggiunge Tailscale-User-Login e toglie le copie del client."""
        login = request.headers.get("Tailscale-User-Login", "").strip().casefold()
        if not login or len(login) > 254:
            raise web.HTTPForbidden(text="Apri JARVIS dalla rete Tailscale.")
        if self.gateway_user and login != self.gateway_user:
            raise web.HTTPForbidden(text="Utente non autorizzato.")
        return login

    # ── snapshot del PC ─────────────────────────────────────────────────
    async def receive_snapshot(self, request):
        self.relay.authorized(request, self.relay.relay_hash)
        try:
            snapshot = _clean_snapshot(await request.json())
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="snapshot non valido")
        self.relay.pc_seen = time.monotonic()
        self.snapshot_file.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        return _json({"ok": True})

    def read_snapshot(self):
        try:
            return json.loads(self.snapshot_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ── pagina e chat a PC spento ───────────────────────────────────────
    async def offline_state(self, request):
        self.identity(request)
        snapshot = self.read_snapshot()
        return _json({
            "pc_alive": self.relay.pc_alive(),
            "snapshot": snapshot,
            "snapshot_age_sec": int(time.time() - snapshot["sent_at"]) if snapshot else None,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    async def offline_ask(self, request):
        self.identity(request)
        if self.relay.pc_alive():
            return _json({"ok": False, "error": "PC acceso: usa la dashboard."}, status=409)
        try:
            body = await request.json()
            text = body.get("text") if isinstance(body, dict) else None
        except (ValueError, TypeError):
            text = None
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            return _json({"ok": False, "error": "Messaggio vuoto o troppo lungo."}, status=400)
        try:
            reply = await self.relay.answer(text.strip(), OFFLINE_CHAT)
        except Exception:  # noqa: BLE001 — errore API o budget: risposta leggibile
            return _json({"ok": False, "error": "Non riesco a rispondere ora. Riprova tra poco."}, status=502)
        return _json({"ok": True, "reply": reply})

    # ── proxy verso il PC ───────────────────────────────────────────────
    def upstream_headers(self, request, login):
        headers = CIMultiDict((k, v) for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP)
        headers["Origin"] = self.pc_live_url
        headers["X-Jarvis-Gateway"] = self.gateway_token
        headers["X-Jarvis-User"] = login
        if request.headers.get("Cookie"):
            headers["Cookie"] = request.headers["Cookie"]
        return headers

    def local_static(self, request):
        """File di web/public da servire qui, o None. Solo lista esplicita, niente percorsi liberi."""
        if request.method not in ("GET", "HEAD") or request.path not in LOCAL_STATIC:
            return None
        path = (STATIC_DIR / request.path.lstrip("/")).resolve()
        if not path.is_file() or not path.is_relative_to(STATIC_DIR.resolve()):
            return None
        return path

    async def proxy(self, request):
        login = self.identity(request)
        local = self.local_static(request)
        if local is not None:
            return web.FileResponse(local, headers={"Cache-Control": "no-cache"})
        if not self.relay.pc_alive():
            if request.method == "GET" and request.path == "/":
                return web.FileResponse(self.offline_page, headers={"Cache-Control": "no-store"})
            return _json({"error": "PC spento: questa funzione torna a PC acceso."}, status=503)
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self.proxy_socket(request, login)
        body = await request.read()
        timeout = ClientTimeout(total=180, sock_connect=5)
        try:
            async with self.session.request(request.method, self.pc_live_url + request.raw_path, data=body or None,
                                            headers=self.upstream_headers(request, login), timeout=timeout,
                                            allow_redirects=False) as upstream:
                # Streaming: il browser riceve i primi byte senza aspettare tutto il corpo.
                headers = CIMultiDict((k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP)
                response = web.StreamResponse(status=upstream.status, headers=headers)
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (OSError, asyncio.TimeoutError):
            return _json({"error": "PC non raggiungibile: riprova tra poco."}, status=503)

    async def proxy_socket(self, request, login):
        inbound = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_FRAME)
        await inbound.prepare(request)
        url = self.pc_live_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + request.raw_path
        try:
            async with self.session.ws_connect(url, headers=self.upstream_headers(request, login),
                                               max_msg_size=MAX_FRAME, heartbeat=20) as outbound:
                async def pump(source, sink):
                    async for message in source:
                        if message.type == WSMsgType.TEXT:
                            await sink.send_str(message.data)
                        elif message.type == WSMsgType.BINARY:
                            await sink.send_bytes(message.data)
                        elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                            break
                tasks = [asyncio.create_task(pump(inbound, outbound)), asyncio.create_task(pump(outbound, inbound))]
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        except (OSError, asyncio.TimeoutError):
            await inbound.close(code=1011, message=b"PC non raggiungibile")
        return inbound

    def attach(self, app):
        """Rotte del gateway: prima quelle specifiche, poi tutto il resto verso il PC.
        Chiamare dopo le rotte della VPS (/telegram/updates, /watch/ask)."""
        app.router.add_post("/pc/snapshot", self.receive_snapshot)
        app.router.add_get("/offline/state", self.offline_state)
        app.router.add_post("/offline/ask", self.offline_ask)
        app.router.add_route("*", "/{tail:.*}", self.proxy)

        async def lifecycle(app):
            # CA di certifi: lo store della VPS non ha tutte le radici (vedi relay.py).
            import ssl
            import certifi
            from aiohttp import TCPConnector
            connector = TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))
            self.session = ClientSession(connector=connector)
            yield
            await self.session.close()
        app.cleanup_ctx.append(lifecycle)
