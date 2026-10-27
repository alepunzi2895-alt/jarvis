import asyncio
import base64
import io
import time
import wave
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import CookieJar, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from core.live_server import create_app, LiveServer, COOKIE
from core.voice.streaming import SentenceBuffer, finish_thread
# Il server lo importa al primo audio: a freddo supera il timeout dei test WebSocket.
import core.web_bridge  # noqa: F401


class FakeEngine:
    ready = True
    device = "cpu"

    def __init__(self):
        self.commands = []
        self.cancelled = []
        self.release = asyncio.Event()

    def transcribe(self, raw):
        return raw.decode()

    async def synthesize(self, text):
        return text.encode()

    async def respond(self, prompt, image, history, sentence, **options):
        self.commands.append(prompt)
        await sentence("Prima frase.")
        if prompt == "attendi":
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.append(prompt)
                raise
        await sentence("Seconda frase.")
        return dict(result="Prima frase. Seconda frase.", workspace="jarvis", cost_usd=0)


async def client_for(engine=None):
    app = create_app("test-password", [], engine=engine or FakeEngine(), warm=False)
    server = next(v for v in app.values() if isinstance(v, LiveServer))
    client = TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True))
    await client.start_server()
    origin = str(client.make_url("/")).rstrip("/")
    server.origins.add(origin)
    server.hosts.add(client.make_url("/").host_port_subcomponent)
    client.session.headers["Origin"] = origin
    return client, server


async def login(client):
    response = await client.post("/api/jarvis", json={"action": "login", "password": "test-password"})
    assert response.status == 200
    return response


def test_memory_and_connected_data_require_login_and_forget_persists(monkeypatch):
    from core import conversation_memory as memory, tradepilot, azure_devops
    memory.handle_command('ricorda che preferisco i dettagli scritti')
    monkeypatch.setattr(tradepilot, 'snapshot', lambda: {'connected': True, 'curve': []})
    monkeypatch.setattr(azure_devops, 'snapshot', lambda: {'connected': False, 'error': 'Accesso richiesto'})
    async def run():
        client, server = await client_for()
        async with client:
            for action in ('memories_list','tradepilot_data','devops_data'):
                assert (await client.post('/api/jarvis',json={'action':action})).status == 401
            await login(client)
            rows = await (await client.post('/api/jarvis',json={'action':'memories_list'})).json()
            assert len(rows['memories']) == 1
            assert (await (await client.post('/api/jarvis',json={'action':'tradepilot_data'})).json())['connected']
            assert not (await (await client.post('/api/jarvis',json={'action':'devops_data'})).json())['connected']
            await client.post('/api/jarvis',json={'action':'memory_forget','id':rows['memories'][0]['id']})
            assert not memory.entries()
    asyncio.run(run())


def test_project_widget_reads_live_dynamic_catalog_and_caches(monkeypatch):
    from core import project_status
    check = Mock(return_value=[project_status.ProjectStatus("new", "Nuovo", None, False)])
    monkeypatch.setattr(project_status, "check_all", check)
    async def run():
        client, server = await client_for()
        async with client:
            await login(client)
            for _ in range(2):
                response = await client.post("/api/jarvis", json={"action": "project_status_data"})
                assert (await response.json())["projects"][0]["key"] == "new"
            assert check.call_count == 1
    asyncio.run(run())


async def until(socket, kind, rid=None):
    messages = []
    for _ in range(25):
        message = await socket.receive_json(timeout=3)
        messages.append(message)
        if message["type"] == kind and (rid is None or message.get("id") == rid):
            return messages
    pytest.fail(f"Evento {kind} assente")


def test_auth_origin_password_logout_and_no_cloud_fallback():
    async def scenario():
        client, server = await client_for()
        async with client:
            assert (await client.post("/api/jarvis", json={"action": "tasks_recent"})).status == 401
            assert (await client.post("/api/jarvis", json={"action": "coding_tasks"})).status == 401
            with pytest.raises(WSServerHandshakeError):
                await client.ws_connect("/live/ws")
            assert (await client.post("/api/jarvis", json={"action": "login", "password": "wrong"})).status == 401
            response = await login(client)
            assert (await (await client.post('/api/jarvis', json={'action':'coding_tasks'})).json())['jobs'] == []
            assert response.cookies[COOKIE]["httponly"]
            assert response.cookies[COOKIE]["samesite"] == "Strict"
            for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}):
                assert (await client.post("/api/jarvis", headers=headers, json={"action": "tasks_recent"})).status == 403
            with pytest.raises(WSServerHandshakeError):
                await client.ws_connect("/live/ws", headers={"Origin": "https://evil.example"})
            assert (await client.post("/api/jarvis", json={"action": "task_push", "audio_b64": "private"})).status == 400
            socket = await client.ws_connect("/live/ws")
            await until(socket, "ready")
            await client.post("/api/jarvis", json={"action": "logout"})
            assert (await client.post("/api/jarvis", json={"action": "tasks_recent"})).status == 401
            await socket.close()
    asyncio.run(scenario())


def test_login_rate_limit_and_session_expiry():
    async def scenario():
        client, server = await client_for()
        async with client:
            await login(client)
            for session in server.sessions.values():
                session["expires"] = time.monotonic() - 1
            assert (await client.post("/api/jarvis", json={"action": "tasks_recent"})).status == 401
            for _ in range(10):
                await client.post("/api/jarvis", json={"action": "login", "password": "wrong"})
            assert (await client.post("/api/jarvis", json={"action": "login", "password": "test-password"})).status == 429
    asyncio.run(scenario())


def test_stream_order_noise_does_not_cancel_and_wake_followup():
    async def scenario():
        engine = FakeEngine()
        client, server = await client_for(engine)
        async with client:
            await login(client)
            socket = await client.ws_connect("/live/ws")
            await until(socket, "ready")
            await socket.send_json(dict(type="text", id="one", prompt="attendi"))
            early = await until(socket, "audio", "one")
            assert any(m["type"] == "sentence" for m in early)
            assert not any(m["type"] == "result" for m in early)
            await socket.send_json(dict(type="audio", id="noise", data=base64.b64encode(b"Alla prossima!").decode()))
            await until(socket, "ignored", "noise")
            assert engine.cancelled == []
            engine.release.set()
            rest = await until(socket, "done", "one")
            audio = [base64.b64decode(m["data"]).decode() for m in early + rest if m["type"] == "audio"]
            assert audio == ["Prima frase.", "Seconda frase."]
            for rid, text, last in [("wake", "Jarvis.", "ignored"), ("two", "come stai", "done")]:
                await socket.send_json(dict(type="audio", id=rid, data=base64.b64encode(text.encode()).decode()))
                await until(socket, last, rid)
            assert engine.commands == ["attendi", "come stai"]
            history = await (await client.post("/api/jarvis", json={"action": "tasks_recent"})).json()
            assert len(history["tasks"]) == 2
            assert all("audio_b64" not in row and "data" not in row for row in history["tasks"])
            await socket.close()
    asyncio.run(scenario())


def test_valid_replacement_cancels_old_turn_and_disconnect_cleans_up():
    async def scenario():
        engine = FakeEngine()
        client, server = await client_for(engine)
        async with client:
            await login(client)
            socket = await client.ws_connect("/live/ws")
            await until(socket, "ready")
            await socket.send_json(dict(type="text", id="old", prompt="attendi"))
            await until(socket, "audio", "old")
            await socket.send_json(dict(type="text", id="new", prompt="ciao"))
            events = await until(socket, "done", "new")
            assert engine.cancelled == ["attendi"]
            assert any(m["type"] == "cancelled" and m["id"] == "old" for m in events)
            await socket.send_json(dict(type="text", id="disconnect", prompt="attendi"))
            await until(socket, "audio", "disconnect")
            await socket.close()
            for _ in range(50):
                if not server.command_lock.locked():
                    break
                await asyncio.sleep(.01)
            assert not server.command_lock.locked()
            assert len(engine.cancelled) == 2
    asyncio.run(scenario())


def test_parallel_clients_are_bounded_and_cancel_stops_synthesis():
    async def scenario():
        engine = FakeEngine()
        client, server = await client_for(engine)
        async with client:
            await login(client)
            a = await client.ws_connect("/live/ws")
            b = await client.ws_connect("/live/ws")
            await until(a, "ready")
            await until(b, "ready")
            await a.send_json(dict(type="text", id="a", prompt="attendi"))
            await until(a, "audio", "a")
            await b.send_json(dict(type="text", id="b", prompt="ciao"))
            await until(b, "error", "b")
            assert engine.commands == ["attendi"]
            await a.send_json(dict(type="cancel"))
            await until(a, "cancelled", "a")
            await a.send_json(dict(type="status"))
            await until(a, "ready")
            assert not server.command_lock.locked()
            await a.close()
            await b.close()
    asyncio.run(scenario())


def test_wav_format_validation_before_inference(monkeypatch):
    from core.voice import stt
    model = Mock()
    monkeypatch.setattr(stt, "_get_model", model)
    for channels, rate, seconds in [(2, 16000, 1), (1, 16000, 21), (1, 4000, 1)]:
        data = io.BytesIO()
        with wave.open(data, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(b"\0\0" * rate * seconds * channels)
        with pytest.raises(ValueError):
            stt.transcribe_wav(data.getvalue())
    model.assert_not_called()


def test_sentence_buffer_hides_split_fences_and_flushes_last_sentence():
    buffer = SentenceBuffer()
    spoken = []
    for delta in ["Ecco. ", "Apro Chrome", "`", "``system\n", '{"action":"open"}', "```\nNon leggere"]:
        spoken += buffer.feed(delta)
    spoken += buffer.finish()
    assert spoken == ["Ecco.", "Apro Chrome"]
    buffer = SentenceBuffer()
    assert buffer.feed("Ciao") == []
    assert buffer.finish() == ["Ciao"]


def test_cancel_waits_for_os_thread_before_releasing_lock():
    import threading
    async def scenario():
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def work():
            started.set()
            release.wait(3)
            finished.set()
        task = asyncio.create_task(finish_thread(work))
        while not started.is_set():
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    asyncio.run(scenario())


def test_live_uses_voice_model_without_changing_text_model(monkeypatch):
    from core.live_server import Engine
    from core import claude_bridge as bridge, intents
    monkeypatch.setattr(intents, "parse_intent", lambda prompt: None)
    monkeypatch.setattr(bridge, "TEXT_ENGINE", "api")
    monkeypatch.setattr(bridge, "VOICE_MODEL", "haiku")
    answer = AsyncMock(return_value=("Pronto.", None, .001))
    monkeypatch.setattr(bridge, "_run_claude_api", answer)
    old_text_model = bridge.API_MODEL
    engine = Engine()
    engine.contexts["jarvis"] = "Contesto caldo"
    asyncio.run(engine.respond("ciao", None, {}, AsyncMock()))
    kwargs = answer.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert "Contesto caldo" in kwargs["context_prefix"]
    assert "15 parole" in kwargs["context_prefix"]
    assert bridge.API_MODEL == old_text_model


def test_live_captures_webcam_frame_when_asked_to_see(monkeypatch):
    from core.live_server import Engine
    from core import claude_bridge as bridge
    from core.voice import camera
    monkeypatch.setattr(bridge, "TEXT_ENGINE", "api")
    monkeypatch.setattr(camera, "capture_frame_b64", lambda: "frame64")
    answer = AsyncMock(return_value=("Vedo una scrivania.", None, .001))
    monkeypatch.setattr(bridge, "_run_claude_api", answer)
    engine = Engine()
    engine.contexts["jarvis"] = "Contesto"
    asyncio.run(engine.respond("cosa vedi dalla webcam", None, {}, AsyncMock()))
    assert answer.call_args.args[3] == "frame64"
    # Immagine gia' allegata dal pannello camera: nessuna seconda cattura.
    monkeypatch.setattr(camera, "capture_frame_b64", Mock(side_effect=AssertionError))
    asyncio.run(engine.respond("cosa vedi dalla webcam", "client64", {}, AsyncMock()))
    assert answer.call_args.args[3] == "client64"


def test_live_reports_missing_webcam_instead_of_asking_claude(monkeypatch):
    from core.live_server import Engine
    from core import claude_bridge as bridge
    from core.voice import camera
    monkeypatch.setattr(camera, "capture_frame_b64", lambda: None)
    answer = AsyncMock()
    monkeypatch.setattr(bridge, "_run_claude_api", answer)
    spoken = AsyncMock()
    result = asyncio.run(Engine().respond("scatta una foto", None, {}, spoken))
    assert result["result"] == "Non riesco ad aprire la webcam del PC."
    spoken.assert_awaited_once_with("Non riesco ad aprire la webcam del PC.")
    answer.assert_not_called()


def test_stop_during_replacement_never_launches_waiting_command():
    import threading
    async def scenario():
        class SlowEngine(FakeEngine):
            def __init__(self):
                super().__init__()
                self.started = threading.Event()
                self.stop_requested = asyncio.Event()
                self.finished = threading.Event()
                self.release_thread = threading.Event()
            async def respond(self, prompt, image, history, sentence, **options):
                self.commands.append(prompt)
                if prompt == "slow":
                    def work():
                        self.started.set()
                        self.release_thread.wait(3)
                        self.finished.set()
                    task = asyncio.create_task(finish_thread(work))
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        self.stop_requested.set()
                        await task
                        raise
                return dict(result="Finito.", workspace="jarvis", cost_usd=0)
        engine = SlowEngine()
        client, server = await client_for(engine)
        async with client:
            await login(client)
            socket = await client.ws_connect("/live/ws")
            await until(socket, "ready")
            await socket.send_json(dict(type="text", id="old", prompt="slow"))
            while not engine.started.is_set():
                await asyncio.sleep(.01)
            await socket.send_json(dict(type="text", id="replacement", prompt="new"))
            await asyncio.wait_for(engine.stop_requested.wait(), 1)
            await socket.send_json(dict(type="cancel"))
            await asyncio.sleep(.03)
            assert engine.commands == ["slow"]
            engine.release_thread.set()
            await socket.send_json(dict(type="status"))
            events = await until(socket, "ready")
            assert not any(m["type"] == "accepted" and m.get("id") == "replacement" for m in events)
            assert engine.commands == ["slow"]
            assert engine.finished.is_set()
            await socket.close()
    asyncio.run(scenario())


def test_text_command_supersedes_audio_still_transcribing():
    import threading
    async def scenario():
        class SlowSttEngine(FakeEngine):
            def __init__(self):
                super().__init__()
                self.stt_started = threading.Event()
                self.stt_release = threading.Event()
            def transcribe(self, raw):
                self.stt_started.set()
                self.stt_release.wait(3)
                return raw.decode()
        engine = SlowSttEngine()
        client, server = await client_for(engine)
        async with client:
            await login(client)
            socket = await client.ws_connect("/live/ws")
            await until(socket, "ready")
            await socket.send_json(dict(type="audio", id="late", data=base64.b64encode(b"Jarvis apri il browser").decode()))
            while not engine.stt_started.is_set():
                await asyncio.sleep(.01)
            # Pulsante premuto mentre la CPU trascrive ancora rumore o voce.
            await socket.send_json(dict(type="text", id="button", prompt="ciao"))
            events = await until(socket, "done", "button")
            assert not any(m["type"] == "error" for m in events)
            assert any(m["type"] == "ignored" and m["id"] == "late" for m in events)
            engine.stt_release.set()
            for _ in range(100):
                if not server.stt_lock.locked():
                    break
                await asyncio.sleep(.01)
            await socket.send_json(dict(type="status"))
            rest = await until(socket, "ready")
            assert not any(m.get("id") == "late" for m in rest)
            assert engine.commands == ["ciao"]
            await socket.close()
    asyncio.run(scenario())


def test_desktop_console_presence_gates_pc_wake_word():
    from core import console_presence
    async def scenario():
        client, server = await client_for()
        async with client:
            await login(client)
            phone = await client.ws_connect("/live/ws")
            await until(phone, "ready")
            assert not console_presence.read_open()
            pc = await client.ws_connect("/live/ws?pc=1")
            await until(pc, "ready")
            assert console_presence.read_open()
            await pc.close()
            for _ in range(50):
                if not console_presence.read_open():
                    break
                await asyncio.sleep(0.02)
            assert not console_presence.read_open()
            await phone.close()
    asyncio.run(scenario())


def test_console_presence_stale_heartbeat_counts_as_closed(monkeypatch):
    import json
    from core import console_presence
    console_presence.write(1)
    assert console_presence.read_open()
    console_presence.PATH.write_text(json.dumps({"clients": 1, "ts": time.time() - console_presence.STALE_SEC - 1}))
    assert not console_presence.read_open()
    console_presence.PATH.write_text("non json")
    assert not console_presence.read_open()


def test_watch_endpoint_uses_bearer_token_without_cookie_or_origin():
    async def scenario():
        engine = FakeEngine()
        app = create_app("test-password", [], engine=engine, warm=False, watch_token="watch-secret")
        server = next(v for v in app.values() if isinstance(v, LiveServer))
        client = TestClient(TestServer(app))
        await client.start_server()
        server.hosts.add(client.make_url("/").host_port_subcomponent)
        async with client:
            assert (await client.post("/watch/ask", json={"text": "ciao"})).status == 401
            wrong = {"Authorization": "Bearer sbagliato"}
            assert (await client.post("/watch/ask", headers=wrong, json={"text": "ciao"})).status == 401
            good = {"Authorization": "Bearer watch-secret"}
            assert (await client.post("/watch/ask", headers=good, json={})).status == 400
            response = await client.post("/watch/ask", headers=good, json={"text": "che ore sono"})
            assert response.status == 200
            assert await response.text() == "Prima frase. Seconda frase."
            assert engine.commands == ["che ore sono"]
            # Il resto dell'API resta protetto da Origin e cookie.
            assert (await client.post("/api/jarvis", json={"action": "tasks_recent"})).status == 403
            for _ in range(8):
                await client.post("/watch/ask", headers=wrong, json={"text": "x"})
            assert (await client.post("/watch/ask", headers=good, json={"text": "x"})).status == 429
    asyncio.run(scenario())


def test_outlook_web_endpoint_needs_watch_token_and_serves_other_processes(monkeypatch):
    """Piano B Outlook: bot.py e daemon vocale leggono Outlook Web tramite
    LiveBridge, che possiede il browser JARVIS."""
    from core import outlook_web
    seen = []

    async def run(action, params):
        seen.append((action, params))
        if action == "unread":
            raise outlook_web.OutlookWebError("serve di nuovo l'accesso Microsoft")
        return [{"subject": "Daily"}]

    monkeypatch.setattr(outlook_web, "run", run)

    async def scenario():
        app = create_app("test-password", [], engine=FakeEngine(), warm=False, watch_token="watch-secret")
        server = next(v for v in app.values() if isinstance(v, LiveServer))
        client = TestClient(TestServer(app))
        await client.start_server()
        server.hosts.add(client.make_url("/").host_port_subcomponent)
        async with client:
            body = {"action": "events", "params": {"day": "2026-10-27"}}
            assert (await client.post(outlook_web.PATH, json=body)).status == 401
            good = {"Authorization": "Bearer watch-secret"}
            assert (await client.post(outlook_web.PATH, headers=good, json=[])).status == 400
            response = await client.post(outlook_web.PATH, headers=good, json=body)
            assert await response.json() == {"ok": True, "result": [{"subject": "Daily"}]}
            # Client sincrono degli altri processi, da un thread come nei tool.
            monkeypatch.setattr(outlook_web, "_live_endpoint", lambda: (client.port, "watch-secret"))
            assert await asyncio.to_thread(outlook_web.call_sync, "events", day="2026-10-28") == [{"subject": "Daily"}]
            with pytest.raises(outlook_web.OutlookWebError, match="accesso Microsoft"):
                await asyncio.to_thread(outlook_web.call_sync, "unread")
        assert seen[-2:] == [("events", {"day": "2026-10-28"}), ("unread", {})]
    asyncio.run(scenario())


def test_iveco_panel_actions_require_login_and_run_recap_once(monkeypatch):
    from core import iveco, coding_tasks
    calls = []
    def build(loop=None):
        assert loop is not None  # serve al recap per leggere Teams dal browser
        calls.append(1)
        time.sleep(0.2)
        return {"text": "ok"}
    monkeypatch.setattr(iveco, "build_recap", build)
    monkeypatch.setattr(iveco, "latest", lambda: {"text": "ultimo"})
    monkeypatch.setattr(iveco, "jobs_panel", lambda: {"prd": {"overall": {"sample_runs": 1}}})
    started = []
    monkeypatch.setattr(coding_tasks, "start_task", lambda *a: started.append(a))
    monkeypatch.setattr(coding_tasks, "list_tasks", lambda job_id, project: [{"project": project}])
    async def run():
        client, server = await client_for()
        async with client:
            for action in ("iveco_recap", "iveco_recap_run", "iveco_jobs", "ivgagent_ask", "ivgagent_tasks"):
                assert (await client.post("/api/jarvis", json={"action": action})).status == 401
            await login(client)
            post = lambda **body: client.post("/api/jarvis", json=body)
            assert (await (await post(action="iveco_recap")).json())["recap"]["text"] == "ultimo"
            await post(action="iveco_recap_run")
            await post(action="iveco_recap_run")  # gia' in corso: nessuna seconda generazione
            assert (await (await post(action="iveco_recap")).json())["running"]
            await server.recap_task
            assert calls == [1]
            assert (await (await post(action="iveco_jobs")).json())["prd"]["overall"]["sample_runs"] == 1
            assert (await post(action="ivgagent_ask", prompt=7)).status == 400
            tasks = await (await post(action="ivgagent_ask", prompt="stato job")).json()
            assert started == [("claude", "IVGAgent", "stato job", "read", "", True)]
            assert tasks["tasks"] == [{"project": "IVGAgent"}]
    asyncio.run(run())
