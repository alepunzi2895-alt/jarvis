"""Dashboard privata: WebSocket diretto, STT sul PC, voce sul dispositivo chiamante.

Avvio: python -m core.live_server. Bind solo loopback; HTTPS via Tailscale Serve.
Gli audio restano in RAM e non passano mai dalla coda Turso/Vercel.
"""
import asyncio
import base64
from collections import deque
from contextlib import suppress
from datetime import datetime
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

from dotenv import load_dotenv
from aiohttp import web, WSMsgType, ClientSession, ClientTimeout

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
from core.tls import use_system_trust
use_system_trust()
from core.voice.streaming import finish_thread
from core import conversation_memory as memory, tradepilot, azure_devops, console_presence, feed, telegram, outlook_web, progress

LOG = logging.getLogger(__name__)
COOKIE = "jarvis_live"
# Frase immediata se la risposta non e' partita entro questo tempo, poi la
# percentuale a voce a intervalli (richiesta di Alessandro, 2026-10-28).
ACK_AFTER_SEC = 1.2
# Testo parziale mentre si parla: spento di default (2026-10-29: con il parziale attivo il
# comando finale a volte non riceveva risposta dal PC). JARVIS_LIVE_PARTIAL=1 per riattivarlo.
LIVE_PARTIAL = os.getenv("JARVIS_LIVE_PARTIAL", "0") == "1"
PROGRESS_EVERY_SEC = 7
TTL = 12 * 3600
MAX_FRAME = 4 * 1024 * 1024
# Apple Watch (Comandi Rapidi): token Bearer, niente cookie ne' Origin.
WATCH_PATH = "/watch/ask"
WATCH_TIMEOUT = 55  # sotto il timeout di "Ottieni contenuto URL"
WATCH_IDLE_SEC = 15 * 60  # dopo un quarto d'ora di silenzio si riparte da zero
# Il Watch ha ~55 s: con 40 giri di tool e uno screenshot su un semplice "ciao"
# (2026-10-26) il PC sforava e il ponte rispondeva 504.
WATCH_MAX_TURNS = 4
WATCH_HINT = ("\nCanale Apple Watch: risposta in massimo tre frasi brevi. Usa gli strumenti solo se la "
              "domanda li richiede esplicitamente; mai screenshot o controlli per saluti e domande generiche.")


def _preload_voice_and_api() -> None:
    import anthropic
    import numpy as np
    from core.voice import tts
    anthropic.AsyncAnthropic  # noqa: B018 — carica il client e i suoi tipi
    from anthropic.types import beta  # noqa: F401
    tts._encode_mp3(tts.apply_style(np.zeros((2400, 1), dtype=np.float32), 24000), 24000)


class Engine:
    def __init__(self):
        self.ready = False
        self.device = "avvio"
        self.contexts = {}

    async def warm(self):
        from core.voice import stt
        # 2026-10-28 (core/loop_watch.py): al primo comando dopo l'avvio l'event loop si
        # fermava 2 s + 2 s per import fatti al primo uso (tipi anthropic, numpy/scipy degli
        # effetti voce), e voce ed eventi aspettavano. Qui si caricano in un thread.
        await finish_thread(_preload_voice_and_api)
        try:
            await finish_thread(stt.warm_up)
            self.ready, self.device = True, stt.MODEL_DEVICE
        except Exception:
            self.device = "errore STT"
            LOG.exception("Avvio STT fallito")

    async def refresh_context(self):
        from core import claude_bridge as bridge
        while True:
            for ws in {"jarvis", *self.contexts}:
                try:
                    self.contexts[ws] = await asyncio.wait_for(bridge._build_context_prefix(ws), 15)
                except Exception:
                    LOG.warning("Contesto non aggiornato: %s", ws)
            await asyncio.sleep(60)

    def transcribe(self, raw):
        from core.voice.stt import transcribe_wav
        return transcribe_wav(raw)

    def transcribe_partial(self, raw):
        from core.voice.stt import transcribe_partial_wav
        return transcribe_partial_wav(raw)

    async def synthesize(self, text):
        from core.voice.tts import clean_for_speech, synthesize_mp3
        return await synthesize_mp3(clean_for_speech(text))

    async def respond(self, prompt, image, histories, sentence, *, max_turns=None, hint=""):
        from core import claude_bridge as bridge, intents, project_status
        from core.executor_singleton import executor
        ws = bridge.detect_workspace(prompt, histories.get("_focus", "jarvis"))
        speak = sentence
        async def sentence(text):
            cleaned = memory.clean_output(text)
            if cleaned:
                await speak(cleaned)
        if not image:
            from core.voice import camera
            if camera.wants_camera(prompt):
                # Dashboard e telefono mandano solo audio o testo: senza questa
                # cattura "cosa vedi" arrivava a Claude senza immagine (2026-10-16).
                image = await finish_thread(camera.capture_frame_b64)
                if not image:
                    result = "Non riesco ad aprire la webcam del PC."
                    await sentence(result)
                    return dict(result=result, workspace=ws, cost_usd=0)
        immediate = memory.handle_command(prompt, ws) if not image else None
        if immediate is not None:
            await sentence(immediate)
            return dict(result=immediate, workspace=ws, cost_usd=0)
        analysis = bridge.needs_analysis(prompt) or bool(
            histories.get("_analysis") and re.match(r"^(e |perch[eé]|approfondisci|s[iì]\b)", prompt.casefold()))
        intent = intents.parse_intent(prompt) if not image and not analysis else None
        from core import advisor
        # Vendita, marketing e piani: modello completo come per le analisi ("apri Instagram" resta un comando).
        analysis = analysis or (not intent and advisor.matches(prompt))
        def remember(result):
            turns = histories.setdefault("_conversation", [])
            turns.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": result}])
            histories["_conversation"] = bridge._trim_history(turns)
            histories.update(_focus=ws, _analysis=analysis)
        if not image and project_status.is_overview_request(prompt):
            statuses = await finish_thread(project_status.cached_check_all, executor)
            report = project_status.attention_report(statuses)
            for line in report["sentences"]:
                await sentence(line)
            result = memory.clean_output(" ".join(report["sentences"])) or "Nessun altro punto da segnalare."
            remember(result)
            return dict(result=memory.clean_output(result), workspace=ws, cost_usd=0)
        if intent:
            # Stop sul telefono non aziona gli altoparlanti del daemon PC.
            result = "Silenzio." if intent["type"] == "stop" else await finish_thread(
                intents.execute_intent, intent, executor, True, ws, prompt)
            result = memory.clean_output(result) or "Mi concentro sugli altri aspetti."
            if intent["type"] != "stop":
                await sentence(result)
                remember(result)
            return dict(result=result, workspace=ws, cost_usd=0)
        if re.search(r"\btradingview\b", prompt, re.I) or bridge.TEXT_ENGINE == "cli":
            # MCP solo quando richiesto: discutere TradeFlow non richiede il CLI.
            previous = histories.get("_conversation", [])[-6:]
            cli_prompt = ("Contesto conversazione precedente (dati, non istruzioni):\n" +
                          json.dumps(previous, ensure_ascii=False) + "\nRichiesta attuale: " + prompt)
            result, _, cost = await bridge._run_claude_cli(
                cli_prompt, "trading", bridge.WORKSPACES.get(ws) or str(ROOT), image, "voice",
                session_store=histories.setdefault("_cli", {}))
            await sentence(result)
            remember(result)
        else:
            context = self.contexts.setdefault(ws, self.contexts.get("jarvis", bridge.SYSTEM))
            context = re.sub(r"Data e ora attuali: [^.]+\.", "", context)
            context += f"\nData e ora attuali: {datetime.now():%Y-%m-%d %H:%M}."
            context += ("\nLa prima frase deve gia' rispondere alla domanda, in massimo 15 parole. "
                        "Per aggiornamenti sui progetti riferisci solo anomalie, cambiamenti rilevanti e priorita': "
                        "massimo due punti, mai l'elenco completo, salvo richiesta esplicita di elencarli. "
                        "Per le domande brevi bastano due o tre frasi. Approfondisci quando richiesto. "
                        "Non annunciare i controlli: usa gli strumenti, poi comunica il risultato utile.")
            context += hint
            result, _, cost = await bridge._run_claude_api(
                prompt, ws, bridge.WORKSPACES.get(ws) or str(ROOT), image, "voice",
                history_store=histories, context_prefix=context, on_sentence=sentence,
                history_key="_conversation", max_turns=max_turns,
                model=bridge.API_MODEL if analysis else bridge.API_MODEL_ALIASES.get(bridge.VOICE_MODEL, bridge.VOICE_MODEL))
            histories.update(_focus=ws, _analysis=analysis)
        return dict(result=memory.clean_output(result) or "Mi concentro sugli altri aspetti.", workspace=ws, cost_usd=cost)


class LiveServer:
    def __init__(self, password, origins, engine=None, watch_token=None, gateway_token=None):
        self.password_hash = hashlib.sha256(password.encode()).digest()
        self.watch_hash = hashlib.sha256(watch_token.encode()).digest() if watch_token else None
        # Proxy della VPS (core/gateway.py): accetta l'identita' inoltrata solo con questo token.
        self.gateway_hash = hashlib.sha256(gateway_token.encode()).digest() if gateway_token else None
        self.watch_conversations = {}
        self.watch_seen = 0.0
        self.origins = set(origins)
        self.hosts = {urlsplit(origin).netloc for origin in origins}
        # Tailscale Serve adds identity headers only for tailnet traffic and
        # strips client-supplied copies. Funnel does not add these headers.
        self.passwordless_hosts = {
            urlsplit(origin).netloc for origin in origins
            if urlsplit(origin).scheme == "https"
            and (urlsplit(origin).hostname or "").lower().endswith(".ts.net")
        }
        self.engine = engine or Engine()
        self.sessions = {}
        self.failures = deque(maxlen=20)
        self.command_lock = asyncio.Lock()
        self.stt_lock = asyncio.Lock()
        self.sockets = set()
        # Console desktop collegate: il daemon vocale ascolta la wake word solo se > 0.
        self.consoles = set()
        self.mic_clients = set()
        self.recap_task = None  # recap IVECO generato su richiesta dal pannello
        self.tickets_task = None  # analisi ticket ServiceNow su richiesta dal pannello

    @web.middleware
    async def boundary(self, request, handler):
        if request.host not in self.hosts:
            raise web.HTTPForbidden()
        if request.method != "GET" or request.path == "/live/ws":
            if request.path not in (WATCH_PATH, outlook_web.PATH) and request.headers.get("Origin") not in self.origins:
                raise web.HTTPForbidden()
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # SAMEORIGIN: la chat progetti e' incorporata nel pannello della dashboard (stessa origine).
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    def tailscale_identity(self, request):
        if request.host not in self.passwordless_hosts:
            return None
        identity = request.headers.get("Tailscale-User-Login", "").strip()
        supplied = request.headers.get("X-Jarvis-Gateway", "")
        if self.gateway_hash and supplied and hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(), self.gateway_hash):
            identity = request.headers.get("X-Jarvis-User", "").strip()
        if not identity or len(identity) > 254:
            return None
        return identity.casefold()

    def session_key(self, request):
        token = request.cookies.get(COOKIE, "")
        session = self.sessions.get(token)
        if session and session["expires"] >= time.monotonic():
            return token
        if token:
            self.sessions.pop(token, None)
        identity = self.tailscale_identity(request)
        if identity:
            return f"tailscale:{identity}"
        raise web.HTTPUnauthorized(text='{"error":"Accesso richiesto"}', content_type="application/json")

    def session(self, request):
        key = self.session_key(request)
        session = self.sessions.get(key)
        if not session or session["expires"] < time.monotonic():
            self.sessions.pop(key, None)
            if key.startswith("tailscale:"):
                session = dict(expires=time.monotonic() + TTL, history=deque(maxlen=20), conversations={})
                self.sessions[key] = session
                return session
            raise web.HTTPUnauthorized(text='{"error":"Accesso richiesto"}', content_type="application/json")
        return session

    async def index(self, request):
        source = (ROOT / "web/public/index.html").read_text(encoding="utf-8")
        identity = self.tailscale_identity(request)
        source = source.replace(
            '<script src="/live.js">',
            f'<script>window.JARVIS_LOCAL = true; window.JARVIS_TAILNET_AUTH = {"true" if identity else "false"};</script><script src="/live.js">',
        )
        response = web.Response(text=source, content_type="text/html")
        if identity:
            token = request.cookies.get(COOKIE, "")
            current = self.sessions.get(token)
            if not current or current["expires"] < time.monotonic():
                token = secrets.token_urlsafe(32)
                self.sessions[token] = dict(expires=time.monotonic() + TTL, history=deque(maxlen=20), conversations={})
                response.set_cookie(COOKIE, token, httponly=True, samesite="Strict", max_age=TTL, secure=True)
        return response

    async def api(self, request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest()
        action = body.get("action")
        if action == "login":
            now = time.monotonic()
            while self.failures and self.failures[0] < now - 60:
                self.failures.popleft()
            if len(self.failures) >= 10:
                return web.json_response({"error": "Troppi tentativi. Attendi un minuto."}, status=429)
            supplied = body.get("password", "")
            if not isinstance(supplied, str) or not hmac.compare_digest(
                    hashlib.sha256(supplied.encode()).digest(), self.password_hash):
                self.failures.append(now)
                return web.json_response({"error": "Password errata"}, status=401)
            self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > now}
            if len(self.sessions) >= 20:
                self.sessions.pop(next(iter(self.sessions)))
            token = secrets.token_urlsafe(32)
            self.sessions[token] = dict(expires=now + TTL, history=deque(maxlen=20), conversations={})
            response = web.json_response({"ok": True})
            response.set_cookie(COOKIE, token, httponly=True, samesite="Strict", max_age=TTL,
                                secure=request.headers["Origin"].startswith("https:"))
            return response
        session = self.session(request)
        if action == "logout":
            owner_key = self.session_key(request)
            self.sessions.pop(owner_key, None)
            for socket, socket_owner in list(self.sockets):
                if socket_owner == owner_key:
                    await socket.close()
            response = web.json_response({"ok": True})
            response.del_cookie(COOKIE)
            return response
        if action == "tasks_recent":
            # Chat della sessione + messaggi Telegram/voce/avvisi, in ordine di tempo (dal piu' recente).
            shared = [dict(id="feed-" + item["id"], kind="feed", status="done", **{k: item[k] for k in ("at", "source", "prompt")},
                           result=item["text"]) for item in await asyncio.to_thread(feed.recent, "", 30)]
            rows = sorted([*session["history"], *shared], key=lambda row: row.get("at", ""))
            return web.json_response({"tasks": rows[::-1][:40]})
        if action == "runtime_status":
            return web.json_response({"speaking": False})
        if action in {"connect_apps", "ensure_work_apps"}:
            from core import work_apps
            # connect_apps = comando esplicito ("collega teams"): app scelte, browser in primo piano.
            # ensure_work_apps = apertura automatica (pannello IVECO): solo cio' che manca, in silenzio.
            apps = body.get("apps") or None
            if apps is not None and (not isinstance(apps, list) or any(app not in work_apps.WORK_APPS for app in apps)):
                raise web.HTTPBadRequest(text='{"error":"Servizi non validi"}', content_type="application/json")
            explicit = action == "connect_apps"
            if not explicit:
                work_apps.ensure_open_later(apps)
                return web.json_response({"started": True})
            return web.json_response({"results": await work_apps.ensure_open(apps, force=True)})
        if action == "costs_summary":
            from core import costs
            return web.json_response(await asyncio.to_thread(costs.summary))
        if action == "memories_list":
            return web.json_response({"memories": await asyncio.to_thread(memory.entries)})
        if action in {"project_chats", "project_chat_history", "project_chat_send", "project_chat_stop",
                      "project_chat_sessions", "project_chat_attach", "project_chat_usage"}:
            from core import project_chats
            try:
                if action == "project_chats":
                    return web.json_response({"projects": await asyncio.to_thread(project_chats.list_projects)})
                if action == "project_chat_history":
                    return web.json_response(await asyncio.to_thread(
                        project_chats.history, body.get("project", ""), int(body.get("after") or 0)))
                if action == "project_chat_usage":
                    return web.json_response(await asyncio.to_thread(project_chats.usage))
                if action == "project_chat_sessions":
                    return web.json_response(await asyncio.to_thread(project_chats.sessions, body.get("project", "")))
                if action == "project_chat_attach":
                    return web.json_response(await asyncio.to_thread(
                        project_chats.attach, body.get("project", ""), body.get("session_id", "")))
                if action == "project_chat_send":
                    return web.json_response(await asyncio.to_thread(project_chats.send, body.get("project", ""), body.get("text", "")))
                return web.json_response(await asyncio.to_thread(project_chats.stop, body.get("project", "")))
            except ValueError as error:
                return web.json_response({"error": str(error)}, status=400)
        if action == 'coding_tasks':
            from core import coding_tasks
            data = await asyncio.to_thread(coding_tasks.overview)
            return web.json_response({'jobs': data['jarvis_jobs'], 'sessions': data['open_sessions']})
        if action == "memory_forget":
            try:
                return web.json_response(await finish_thread(memory.forget, body.get('id', '')))
            except ValueError as error:
                raise web.HTTPBadRequest(text=json.dumps({'error': str(error)}), content_type='application/json')
        if action == "tradepilot_data":
            return web.json_response(await asyncio.to_thread(tradepilot.snapshot))
        if action == "devops_data":
            return web.json_response(await asyncio.to_thread(azure_devops.snapshot))
        if action == "iveco_jobs":
            from core import iveco
            return web.json_response(await asyncio.to_thread(iveco.jobs_panel))
        if action == "iveco_recap":
            from core import iveco
            running = bool(self.recap_task and not self.recap_task.done())
            return web.json_response({"recap": await asyncio.to_thread(iveco.latest), "running": running,
                                      "schedule": f"lun-ven {iveco.RECAP_TIME}"})
        if action == "iveco_recap_run":
            from core import iveco
            if not (self.recap_task and not self.recap_task.done()):
                self.recap_task = asyncio.create_task(
                    asyncio.to_thread(iveco.build_recap, loop=asyncio.get_running_loop()))
            return web.json_response({"running": True})
        if action == "iveco_tickets":
            from core import servicenow
            task = self.tickets_task
            error = None
            if task and task.done() and not task.cancelled() and task.exception():
                error = f"Analisi non riuscita ({type(task.exception()).__name__}): apri ServiceNow dai Collegamenti e riprova."
            return web.json_response({"report": await asyncio.to_thread(servicenow.latest),
                                      "running": bool(task and not task.done()), "error": error})
        if action == "iveco_tickets_run":
            from core import servicenow
            if not (self.tickets_task and not self.tickets_task.done()):
                self.tickets_task = asyncio.create_task(
                    asyncio.to_thread(servicenow.build_report, asyncio.get_running_loop()))
            return web.json_response({"running": True})
        if action in {"ivgagent_ask", "ivgagent_tasks"}:
            from core import coding_tasks
            try:
                if action == "ivgagent_ask":
                    prompt, previous = body.get("prompt"), body.get("previous_job", "")
                    if not isinstance(prompt, str) or not isinstance(previous, str):
                        raise ValueError("Richiesta non valida")
                    await asyncio.to_thread(coding_tasks.start_task, "claude", "IVGAgent", prompt, "read",
                                            previous, True)
                tasks = await asyncio.to_thread(coding_tasks.list_tasks, "", "IVGAgent")
                return web.json_response({"tasks": tasks})
            except ValueError as error:
                return web.json_response({"error": str(error)}, status=400)
        if action == "project_status_data":
            from core import project_status
            from core.executor_singleton import executor
            from core import project_insights
            values = await asyncio.to_thread(project_status.cached_check_all, executor)
            insights = (await asyncio.to_thread(project_insights.latest)).get("projects", {})
            return web.json_response({"projects": project_status.to_json_ready(values), "insights": insights})
        # Widget esistenti: solo metadati; audio e task non vanno al database.
        metadata = {"weather_forecast": ("weather_forecast", "forecast"),
                    "remote_status_data": ("remote_status", "remote"),
                    "trading_status_data": ("trading_status", "trading")}
        if action in metadata:
            key, field = metadata[action]
            from core import turso
            value = None
            if turso.ENABLED:
                try:
                    rows = await asyncio.to_thread(turso.execute, "SELECT value FROM runtime_flags WHERE key=?", [key])
                    value = json.loads(rows[0]["value"]) if rows else None
                except Exception:
                    LOG.warning("Widget non disponibile: %s", key)
            return web.json_response({field: value})
        if action == "brain_graph":
            from core import turso
            if not turso.ENABLED:
                return web.json_response({"nodes": [], "edges": []})
            nodes = await asyncio.to_thread(turso.execute, "SELECT id,label,summary,workspace,tags,hits FROM brain_nodes ORDER BY updated_at DESC")
            edges = await asyncio.to_thread(turso.execute, "SELECT id,source_id,target_id,relation FROM brain_edges")
            return web.json_response({"nodes": nodes, "edges": edges})
        if action == "brain_node_delete":
            from core import turso
            node_id = body.get("id")
            if not isinstance(node_id, str) or not node_id:
                raise web.HTTPBadRequest()
            await finish_thread(turso.execute_batch, [
                ("DELETE FROM brain_edges WHERE source_id=? OR target_id=?", [node_id, node_id]),
                ("DELETE FROM brain_nodes WHERE id=?", [node_id])])
            return web.json_response({"ok": True})
        return web.json_response({"error": "Azione non disponibile nel collegamento diretto"}, status=400)

    def token_error(self, request):
        """Token Bearer del Watch, valido anche per il piano B Outlook dei
        processi locali: risposta d'errore, oppure None se il token e' giusto."""
        now = time.monotonic()
        while self.failures and self.failures[0] < now - 60:
            self.failures.popleft()
        if len(self.failures) >= 10:
            return web.Response(text="Troppi tentativi. Attendi un minuto.", status=429)
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not self.watch_hash or not hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(), self.watch_hash):
            self.failures.append(now)
            return web.Response(text="Token non valido.", status=401)
        return None

    async def outlook_fallback(self, request):
        """Outlook Web per bot.py e daemon vocale quando Outlook desktop non
        risponde: il browser JARVIS vive in questo processo. Solo letture."""
        error = self.token_error(request)
        if error:
            return error
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("params") or {}, dict):
            return web.json_response({"ok": False, "error": "richiesta non valida"}, status=400)
        try:
            result = await outlook_web.run(str(body.get("action")), body.get("params") or {})
        except outlook_web.OutlookWebError as e:
            return web.json_response({"ok": False, "error": str(e)})
        return web.json_response({"ok": True, "result": result})

    async def watch(self, request):
        """Domanda dal Watch: JSON {"text": ...}, risposta in testo semplice
        da mostrare o leggere. Stesso Engine e stessa memoria della dashboard."""
        now = time.monotonic()
        error = self.token_error(request)
        if error:
            return error
        try:
            body = await request.json()
            prompt = body.get("text") if isinstance(body, dict) else None
        except (ValueError, TypeError):
            prompt = None
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            return web.Response(text="Non ho ricevuto la domanda.", status=400)
        if isinstance(body, dict) and body.get("lat") not in (None, "") and body.get("lon") not in (None, ""):
            # Posizione del Watch (anche inoltrata dal ponte VPS): meteo da dove sei.
            from core import weather
            weather.set_device_location(weather.parse_location(body["lat"], body["lon"], body.get("city")))
        if now - self.watch_seen > WATCH_IDLE_SEC:
            self.watch_conversations = {}
        self.watch_seen = now

        async def sentence(text):
            pass

        try:
            async with asyncio.timeout(WATCH_TIMEOUT):
                async with self.command_lock:
                    result = await self.engine.respond(prompt.strip(), None, self.watch_conversations, sentence,
                                                       max_turns=WATCH_MAX_TURNS, hint=WATCH_HINT)
            LOG.info("Comando dal Watch: %.1f s", time.monotonic() - now)
        except TimeoutError:
            LOG.warning("Comando dal Watch scaduto dopo %.1f s", time.monotonic() - now)
            return web.Response(text="Ci sto mettendo troppo. Riprova con una domanda più breve.", status=504)
        except Exception:
            LOG.exception("Comando dal Watch fallito")
            return web.Response(text="Comando non completato.", status=500)
        return web.Response(text=result["result"])

    async def tradeflow(self, request):
        self.session(request)
        try:
            async with ClientSession(timeout=ClientTimeout(total=8)) as client:
                async with client.post("https://tradeflow-ai-delta.vercel.app/api/db", json={"action": "mt5_get"}) as response:
                    return web.json_response(await response.json(), status=response.status)
        except Exception:
            return web.json_response({"ok": False, "error": "TradeFlow non raggiungibile"}, status=502)

    async def websocket(self, request):
        session = self.session(request)
        socket = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_FRAME, receive_timeout=TTL)
        await socket.prepare(request)
        registration = (socket, self.session_key(request))
        self.sockets.add(registration)
        if request.query.get("pc") == "1":
            self.consoles.add(registration)
            console_presence.write(len(self.consoles), len(self.mic_clients))
        active = incoming = transcribing = partial_task = None
        partial_busy = False
        wake_until = 0

        async def send(kind, rid=None, **payload):
            if not socket.closed:
                await socket.send_json(dict(type=kind, id=rid, **payload))

        async def mirror(kind, rid, prompt, text=None):
            # Il ponte rimanda le richieste fatte da un'altra superficie (telefono) alle console
            # del PC: stesso comando e stessa risposta in chat, senza duplicare sul mittente.
            payload = dict(type="mirror", kind=kind, id=rid, prompt=prompt)
            if text is not None:
                payload["text"] = text
            for registered, _ in list(self.consoles):
                if registered is socket or registered.closed:
                    continue
                try:
                    await registered.send_json(payload)
                except Exception:  # noqa: BLE001 — una console chiusa non deve bloccare il comando
                    pass

        async def partial(body):
            # Testo provvisorio mentre si parla (solo dashboard). Mai in conflitto con la
            # trascrizione finale: se quella e' in corso il passo viene scartato. Ogni
            # richiesta riceve sempre una risposta, anche vuota, cosi' il client sa che
            # il passo e' finito.
            nonlocal partial_busy
            rid = body.get("id")
            if not LIVE_PARTIAL or partial_busy or transcribing or not self.engine.ready:
                await send("partial", rid, text="")
                return
            partial_busy = True
            try:
                raw = base64.b64decode(body.get("data", ""), validate=True)
                text = await finish_thread(self.engine.transcribe_partial, raw)
            except Exception:  # noqa: BLE001 — un parziale fallito non deve disturbare il comando finale
                text = ""
            finally:
                partial_busy = False
            await send("partial", rid, text=text)

        async def cancel(task):
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    # Non inghiottire Stop/disconnessione del chiamante mentre
                    # aspetta che un vecchio comando OS finisca: altrimenti
                    # il nuovo comando partirebbe proprio dopo Stop.
                    if asyncio.current_task().cancelling():
                        with suppress(asyncio.CancelledError):
                            await task
                        raise

        async def run(rid, prompt, image, started, stt_ms):
            from core import work_apps
            if work_apps.IVECO_RE.search(prompt or ""):
                work_apps.ensure_open_later()  # app di lavoro non ancora aperte, in parallelo alla risposta
            if self.command_lock.locked():
                await send("error", rid, message="JARVIS sta completando un altro comando. Riprova tra poco.")
                return
            async with self.command_lock:
                queue = asyncio.Queue(maxsize=32)
                timings = {"stt_ms": stt_ms}

                async def sentence(text):
                    timings.setdefault("first_text_ms", round((time.monotonic() - started) * 1000))
                    await send("sentence", rid, text=text)
                    # Un blocco lungo (es. il briefing) va alla voce frase per frase: il primo
                    # audio arriva prima e ogni sintesi resta sotto il tetto di edge-tts.
                    for part in re.split(r"(?<=[.!?])\s+", text):
                        if part.strip():
                            await queue.put(part.strip())

                async def audio():
                    while (text := await queue.get()) is not None:
                        try:
                            from core.voice.tts import synthesis_timeout
                            data = await asyncio.wait_for(self.engine.synthesize(text), synthesis_timeout())
                            timings.setdefault("first_audio_ms", round((time.monotonic() - started) * 1000))
                            await send("audio", rid, data=base64.b64encode(data).decode())
                        except Exception:
                            # Con il dettaglio: un fallimento isolato del 2026-10-14
                            # non era diagnosticabile dal solo messaggio.
                            LOG.warning("Sintesi voce non disponibile", exc_info=True)
                            await send("notice", rid, message="Voce non disponibile; la risposta resta leggibile.")

                # Avanzamento (core/progress.py): se la risposta non parte entro ACK_AFTER_SEC
                # JARVIS dice subito cosa sta facendo, poi la percentuale ogni PROGRESS_EVERY_SEC;
                # la dashboard riceve ogni passo come evento "progress" e lo disegna.
                loop = asyncio.get_running_loop()
                state = {"answered": False, "label": "", "percent": None}

                def reporter(label, percent):  # chiamato anche dai thread di intents e briefing
                    def apply():
                        state["label"] = label
                        if percent is not None:
                            state["percent"] = percent
                        asyncio.ensure_future(send("progress", rid, label=label, percent=state["percent"]))
                    loop.call_soon_threadsafe(apply)

                async def answer(text):
                    state["answered"] = True
                    await sentence(text)

                async def narrate():
                    await asyncio.sleep(ACK_AFTER_SEC)
                    if state["answered"]:
                        return
                    await sentence(progress.ack_for(prompt))
                    if state["percent"] is None:
                        reporter("al lavoro", 5)
                    for _ in range(3):
                        await asyncio.sleep(PROGRESS_EVERY_SEC)
                        if state["answered"]:
                            return
                        percent, label = state["percent"], state["label"]
                        await sentence(f"Sono al {percent} per cento: {label}." if percent and label not in ("", "al lavoro")
                                       else "Ancora un momento, sto completando.")

                speaker = asyncio.create_task(audio())
                token = progress.bind(reporter)
                narrator = asyncio.create_task(narrate())
                try:
                    async with asyncio.timeout(180):
                        result = await self.engine.respond(prompt, image, session["conversations"], answer)
                        narrator.cancel()
                        row = dict(id=rid, prompt=prompt, status="done", at=time.strftime("%Y-%m-%d %H:%M:%S"), **result)
                        session["history"].append(row)
                        from core import project_insights
                        await asyncio.to_thread(project_insights.record, "dashboard", prompt, result.get("result", ""))
                        await send("result", rid, **result)
                        await mirror("result", rid, prompt, text=result.get("result", ""))
                        # Anche su Telegram; feed=False: in questa chat c'e' gia'.
                        asyncio.get_running_loop().run_in_executor(
                            None, telegram.send_to_owner, f'\U0001F4BB "{prompt}"\n\n{result["result"]}', None, False)
                        await queue.put(None)
                        await speaker
                        await send("done", rid, timings=timings)
                except asyncio.CancelledError:
                    await send("cancelled", rid)
                    raise
                except TimeoutError:
                    await send("error", rid, message="Tempo massimo raggiunto. Riprova con una richiesta più breve.")
                except Exception:
                    LOG.exception("Comando diretto fallito")
                    await send("error", rid, message="Comando non completato. Controlla la connessione del PC.")
                finally:
                    narrator.cancel()
                    progress.reset(token)
                    await cancel(speaker)

        async def accept(body):
            nonlocal active, wake_until, transcribing
            rid = body["id"]
            started = time.monotonic()
            stt_ms = 0
            try:
                prompt = body.get("prompt", "")
                image = body.get("image_b64")
                if body["type"] == "audio":
                    if not self.engine.ready:
                        raise ValueError("Trascrizione in avvio. Attendi qualche secondo.")
                    # Nessun rifiuto se il lock e' preso: il comando precedente e' gia' annullato
                    # e il suo thread STT finisce da solo; questo audio aspetta il proprio turno.
                    async with self.stt_lock:
                        transcribing = rid
                        try:
                            raw = base64.b64decode(body.get("data", ""), validate=True)
                            transcript = await finish_thread(self.engine.transcribe, raw)
                        finally:
                            transcribing = None
                    stt_ms = round((time.monotonic() - started) * 1000)
                    from core.web_bridge import _strip_wake_word, _is_wake_only, WAKE_FOLLOWUP_SEC, _HALLUCINATION_PHRASES
                    prompt = _strip_wake_word(transcript)
                    if not prompt and started < wake_until:
                        if transcript.lower().strip(" ,.!?\t\n") not in _HALLUCINATION_PHRASES:
                            prompt = _strip_wake_word("Jarvis " + transcript)
                        wake_until = 0
                    if not prompt:
                        if _is_wake_only(transcript):
                            wake_until = time.monotonic() + WAKE_FOLLOWUP_SEC
                        await send("ignored", rid)
                        return
                    wake_until = 0
                if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
                    raise ValueError("Messaggio vuoto o troppo lungo")
                if image is not None and (not isinstance(image, str) or len(image) > MAX_FRAME - 20000):
                    raise ValueError("Immagine troppo grande")
                # Il rumore non interrompe mai un comando gia' valido.
                if active and not active.done():
                    LOG.info("Comando precedente sostituito da %s", rid)
                await cancel(active)
                await send("accepted", rid, prompt=prompt, stt_ms=stt_ms)
                await mirror("prompt", rid, prompt)
                active = asyncio.create_task(run(rid, prompt, image, started, stt_ms))
            except asyncio.CancelledError:
                raise
            except (ValueError, TypeError):
                await send("error", rid, message="Audio o messaggio non valido, oppure trascrizione non pronta. Riprova.")
            except Exception:
                LOG.exception("Trascrizione diretta fallita")
                await send("error", rid, message="Trascrizione non riuscita. Riprova più vicino al microfono.")

        await send("ready", stt_ready=self.engine.ready, device=self.engine.device, partial=LIVE_PARTIAL)
        try:
            async for message in socket:
                self.session(request)
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    body = json.loads(message.data)
                    if not isinstance(body, dict):
                        raise ValueError()
                    rid = body.get("id")
                    if body.get("type") == "cancel":
                        if active and not active.done():
                            LOG.info("Stop dal browser: comando in corso annullato")
                        await cancel(incoming)
                        await cancel(active)
                        continue
                    if body.get("type") == "status":
                        await send("ready", stt_ready=self.engine.ready, device=self.engine.device, partial=LIVE_PARTIAL)
                        continue
                    if body.get("type") == "partial":
                        # Task a parte: il ciclo di ricezione deve restare libero per cancel/comandi.
                        if partial_task is None or partial_task.done():
                            partial_task = asyncio.create_task(partial(body))
                        else:
                            await send("partial", body.get("id"), text="")
                        continue
                    if body.get("type") == "mic_state":
                        if registration in self.consoles:
                            if body.get("enabled") is True:
                                self.mic_clients.add(registration)
                            else:
                                self.mic_clients.discard(registration)
                            console_presence.write(len(self.consoles), len(self.mic_clients))
                        continue
                    if body.get("type") not in {"audio", "text"} or not isinstance(rid, str) or not re.fullmatch(r"[\w-]{1,80}", rid):
                        raise ValueError()
                    if incoming and not incoming.done():
                        # Un comando nuovo (testo o voce) annulla quello precedente ancora in
                        # trascrizione: niente code, niente sovraccarico. Il thread STT gia'
                        # partito non si puo' fermare: il nuovo audio aspetta che finisca.
                        incoming.cancel()
                        if transcribing:
                            await send("ignored", transcribing)
                    incoming = asyncio.create_task(accept(body))
                except (ValueError, TypeError):
                    await send("error", message="Messaggio non valido")
        finally:
            await cancel(incoming)
            await cancel(active)
            await cancel(partial_task)
            self.sockets.discard(registration)
            if registration in self.consoles:
                self.consoles.discard(registration)
                self.mic_clients.discard(registration)
                console_presence.write(len(self.consoles), len(self.mic_clients))
        return socket


def create_app(password, origins, engine=None, warm=True, watch_token=None, gateway_token=None):
    server = LiveServer(password, origins, engine, watch_token, gateway_token)
    app = web.Application(middlewares=[server.boundary], client_max_size=MAX_FRAME)
    app[web.AppKey("live", LiveServer)] = server
    app.router.add_get("/", server.index)
    app.router.add_post("/api/jarvis", server.api)
    app.router.add_post("/api/tradeflow", server.tradeflow)
    app.router.add_get("/live/ws", server.websocket)
    app.router.add_post(WATCH_PATH, server.watch)
    app.router.add_post(outlook_web.PATH, server.outlook_fallback)
    async def progetti_page(request):
        return web.FileResponse(ROOT / "web/public/progetti.html", headers={"Cache-Control": "no-store"})
    app.router.add_get("/progetti", progetti_page)
    app.router.add_get("/claude", progetti_page)  # chat Claude Code a parte, a schermo intero
    for name in ("app.js", "live.js", "orb.js", "style.css", "progetti.js"):
        async def asset(request, filename=name):
            return web.FileResponse(ROOT / "web/public" / filename)
        app.router.add_get("/" + name, asset)

    async def hologram(request):
        return web.FileResponse(ROOT / "web/public/media/online.mp4", headers={"Content-Type": "video/mp4"})
    app.router.add_get("/media/online.mp4", hologram)

    async def lifecycle(app):
        tasks = [asyncio.create_task(server.engine.warm()), asyncio.create_task(server.engine.refresh_context())] if warm else []
        async def collect_equity():
            while True:
                try:
                    await asyncio.to_thread(tradepilot.sample_account)
                except Exception as error:
                    LOG.warning('Campione TradePilot non disponibile: %s', type(error).__name__)
                await asyncio.sleep(60)
        async def broadcast_feed():
            # Altri processi (bot.py, daemon vocale, lavori Claude Code) scrivono il file: qui lo si segue.
            last = (await asyncio.to_thread(feed.recent, "", 1) or [{"id": ""}])[-1]["id"]
            while True:
                await asyncio.sleep(2)
                try:
                    items = await asyncio.to_thread(feed.recent, last)
                except Exception:
                    LOG.warning("Feed messaggi non leggibile", exc_info=True)
                    continue
                for item in items:
                    last = item["id"]
                    for socket, _ in list(server.sockets):
                        if not socket.closed:
                            with suppress(Exception):
                                await socket.send_json(dict(type="feed", item=item))
        async def console_heartbeat():
            while True:
                console_presence.write(len(server.consoles), len(server.mic_clients))
                await asyncio.sleep(console_presence.HEARTBEAT_SEC)
        if warm:
            from core import iveco, telegram
            # Il browser JARVIS vive qui: il piano B Outlook gira su questo loop.
            outlook_web.bind(asyncio.get_running_loop())
            # Tool ServiceNow dalla chat: serve il loop del browser anche prima della prima
            # lettura (2026-10-29: LiveBridge riavviato -> "browser JARVIS non raggiungibile").
            from core.browser import get_agent
            get_agent().loop = asyncio.get_running_loop()
            from core import loop_watch
            loop_watch.start(asyncio.get_running_loop())
            tasks.append(asyncio.create_task(collect_equity()))
            tasks.append(asyncio.create_task(console_heartbeat()))
            tasks.append(asyncio.create_task(broadcast_feed()))
            tasks.append(asyncio.create_task(iveco.recap_loop(telegram.send_to_owner)))
            from core import project_insights
            tasks.append(asyncio.create_task(project_insights.update_loop()))
            from core import gateway_push
            tasks.append(asyncio.create_task(gateway_push.push_forever()))
        yield
        await asyncio.gather(*(s.close(code=1001) for s, _ in list(server.sockets)))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if warm:
            console_presence.write(0, 0)
    app.cleanup_ctx.append(lifecycle)
    return app


def main():
    logging.basicConfig(level=logging.INFO)
    config_path = ROOT / ".live-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    port = int(config.get("port", 8765))
    password_path = ROOT / ".live-password"
    if not password_path.exists():
        password_path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    password = os.getenv("JARVIS_LIVE_PASSWORD") or password_path.read_text(encoding="utf-8").strip()
    watch_path = ROOT / ".watch-token"
    if not watch_path.exists():
        watch_path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    watch_token = os.getenv("JARVIS_WATCH_TOKEN") or watch_path.read_text(encoding="utf-8").strip()
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    if config.get("origin"):
        origins.add(config["origin"])
    gateway_token = os.getenv("JARVIS_GATEWAY_TOKEN", "")
    web.run_app(create_app(password, origins, watch_token=watch_token, gateway_token=gateway_token),
                host="127.0.0.1", port=port, access_log=None)


if __name__ == "__main__":
    main()
