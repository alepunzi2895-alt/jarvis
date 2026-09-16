#!/usr/bin/env python3
"""
JARVIS — bridge Telegram <-> Claude Code (headless).
Long polling: nessun tunnel, nessuna porta aperta, nessun URL pubblico.
Gira in parallelo al poller della web dashboard (stesso processo, stesso cervello).
"""

import os
import sys
import json
import html
import asyncio
import datetime as dt

import requests
from dotenv import load_dotenv

# Su Windows, stdout/stderr reindirizzati su file (come fa il wrapper .vbs
# dell'autostart) usano di default la codepage della console (es. cp1252),
# che non sa codificare em-dash, virgolette tipografiche o certi caratteri
# "esotici" (es. spazi tipografici in una mail HTML letta via core/outlook.py).
# Senza questo, un print() su quel testo lancia UnicodeEncodeError — non
# preso da nessun try/except qui, quindi l'intero processo (bot Telegram +
# poller web, stesso processo) crasha in silenzio. Stesso identico bug gia'
# risolto una volta in core/voice/daemon.py, mai applicato qui.
#
# line_buffering=True: un file (non un terminale) usa di default un buffer a
# blocchi — i print() restano invisibili in logs/bot.log finche' il buffer
# non si riempie o il processo termina. Scoperto dal vivo (2026-09-15,
# debug del microfono dashboard): il log era a 0 byte dopo 15+ minuti di
# processo attivo e diversi errori reali gia' capitati - inutile per
# diagnosticare qualunque problema in tempo reale finche' non crasha.
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from core.claude_bridge import (
    WORKSPACES,
    JARVIS_HOME,
    state,
    save_state,
    run_claude,
)
from core import (
    web_bridge,
    intents,
    project_status,
    remote_status,
    screen_context,
    databricks,
    telegram,
    weather,
    turso,
    outlook,
    briefing,
    myfxbook,
    presence,
    vscode_actions,
)
from core.executor_singleton import executor, vault
from core.voice import camera, tts

load_dotenv()

TOKEN = os.environ["TELEGRAM_TOKEN"]
OWNER_ID = int(os.environ["TELEGRAM_OWNER_ID"])

API = f"https://api.telegram.org/bot{TOKEN}"

if vault is None:
    print("vault Obsidian non trovato — /note e /search disabilitati")

# --------------------------------------------------------------------------- telegram


def send(text: str, parse: str | None = None) -> None:
    """Fire-and-forget: non blocca il loop asyncio (gira su thread separato).
    Invio vero in core/telegram.py, condiviso col daemon vocale."""
    asyncio.get_running_loop().run_in_executor(None, telegram.send_to_owner, text, parse)


def _typing_sync() -> None:
    try:
        requests.post(
            f"{API}/sendChatAction",
            json={"chat_id": OWNER_ID, "action": "typing"},
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass


def typing() -> None:
    asyncio.get_running_loop().run_in_executor(None, _typing_sync)


# --------------------------------------------------------------------------- voce locale
#
# "Deve rispondermi sempre vocalmente" (richiesta esplicita 2026-09-14): non
# solo il canale vocale nativo, anche le risposte testo/Telegram escono
# dagli altoparlanti del PC — utile solo se sei fisicamente li'. Rispetta lo
# stesso interruttore /voce on|off gia' usato dal daemon vocale (niente
# nuovo comando: "voce in pausa" deve valere ovunque, non solo per hey
# jarvis). Applicato alle risposte vere e proprie (task Claude, comandi
# rapidi, /progetti) — non a dump di riferimento lunghi (/help, /log,
# /search, /status), che leggere ad alta voce sarebbe solo fastidioso.
# Motore/pulizia markdown/interruttore condivisi con core/web_bridge.py in
# core/voice/tts.py::speak_if_enabled().

speak_locally = tts.speak_if_enabled


# --------------------------------------------------------------------------- comandi


def cmd_help() -> str:
    return (
        "JARVIS\n\n"
        "Scrivi un task: lo eseguo.\n\n"
        "/ws            workspace attivo\n"
        "/ws <nome>     cambia workspace\n"
        "/new           nuova sessione (dimentica contesto chat)\n"
        "/status        stato\n"
        "/progetti      stato git + note JARVIS dei progetti\n"
        "/buongiorno    briefing: meteo + calendario + mail + trading + progetti\n"
        "/log           log di oggi\n"
        "/note <testo>  scrive nella daily note del vault Obsidian\n"
        "/search <query> cerca nelle note del vault\n"
        "/apri <app>    apre un'applicazione (Chrome, VS Code, Obsidian...)\n"
        "/code <progetto> <prompt>  apre il progetto in VS Code e ci lancia Claude Code\n"
        "/run <comando> esegue un comando nel workspace attivo (whitelist)\n"
        "/confirm <token> conferma un'azione in sospeso\n"
        "/deny <token>  annulla un'azione in sospeso\n"
        "/voce on|off   attiva/mette in pausa la voce (hey jarvis + risposte parlate qui)\n"
        "/enroll_face   impara il tuo volto dalla webcam (per il riconoscimento in camera)\n"
        "/genie_prd <domanda>  interroga Databricks Genie in PRODUZIONE (chiede conferma)\n"
        "/sql_prd <query>      query SQL Databricks in PRODUZIONE, sola lettura (chiede conferma)\n"
        "/help          questo messaggio\n\n"
        "Anche scrivendo normale (senza /) riconosco comandi rapidi come "
        '"apri chrome", "chiudi vs code", "alza il volume", "blocca lo '
        'schermo", "fai uno screenshot", "spegni il pc" — eseguiti subito, '
        'senza passare da Claude, incluso "stato progetti" e "controlla la '
        'posta" (Outlook desktop via COM).\n\n'
        "Chiedendo normalmente puoi anche farmi guardare Teams, lo schermo, "
        "o interrogare Databricks Genie (ambiente di test) — questi passano "
        "da Claude, non sono istantanei.\n\n"
        f"Workspaces: {', '.join(WORKSPACES)}"
    )


def cmd_log() -> str:
    today = dt.date.today().isoformat()
    f = JARVIS_HOME / "memory" / "log" / f"{today}.md"
    if not f.exists():
        return "Nessun log oggi."
    return f.read_text()[:3800]


def cmd_status() -> str:
    ws = state["ws"]
    sid = state["sessions"].get(ws)
    return (
        f"Workspace: {ws}\n"
        f"Path: {WORKSPACES.get(ws)}\n"
        f"Sessione: {sid[:8] + '…' if sid else 'nuova'}"
    )


async def handle(text: str) -> None:
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help"):
            return send(cmd_help())

        if cmd == "/ws":
            if not arg:
                return send(f"Workspace: {state['ws']}")
            if arg not in WORKSPACES:
                return send(f"Sconosciuto. Disponibili: {', '.join(WORKSPACES)}")
            state["ws"] = arg
            save_state(state)
            return send(f"Workspace -> {arg}")

        if cmd == "/new":
            state["sessions"].pop(state["ws"], None)
            save_state(state)
            return send("Sessione azzerata.")

        if cmd == "/status":
            return send(cmd_status())

        if cmd == "/progetti":
            statuses = await asyncio.to_thread(project_status.check_all, executor)
            speak_locally(project_status.format_report(statuses, voice=True))
            return send(project_status.format_report(statuses, voice=False))

        if cmd in ("/buongiorno", "/briefing"):
            data = await asyncio.to_thread(briefing.gather_briefing_data, executor)
            speak_locally(briefing.format_briefing(data, voice=True))
            return send(briefing.format_briefing(data, voice=False))

        if cmd == "/log":
            return send(cmd_log())

        if cmd == "/note":
            if not vault:
                return send("Vault Obsidian non configurato.")
            if not arg:
                return send("Uso: /note <testo>")
            p = vault.create_daily_note()
            vault.write_note(p.relative_to(vault.root), arg, mode="append")
            return send(f"Scritto in {p.relative_to(vault.root)}")

        if cmd == "/search":
            if not vault:
                return send("Vault Obsidian non configurato.")
            if not arg:
                return send("Uso: /search <query>")
            hits = vault.search(arg)
            if not hits:
                return send("Nessun risultato.")
            return send("\n".join(str(h) for h in hits[:20]))

        if cmd == "/apri":
            if not arg:
                return send("Uso: /apri <app>")
            result = executor.open_app(arg)
            return send(f"Aperto {arg}." if result.ok else f"Errore: {result.stderr}")

        if cmd == "/code":
            if not arg:
                return send(
                    "Uso: /code <progetto> <prompt>\n"
                    f"Progetti disponibili: {', '.join(sorted(WORKSPACES))}\n"
                    "Prompt vuoto = apre solo VS Code, senza far lavorare Claude Code."
                )
            code_parts = arg.split(maxsplit=1)
            project = code_parts[0]
            code_prompt = code_parts[1] if len(code_parts) > 1 else ""
            path = vscode_actions.resolve_project_path(project)
            if not path:
                return send(f'Progetto "{project}" non riconosciuto o non autorizzato.')
            result = executor.open_vscode(path)
            if not result.ok:
                return send(f"Errore: {result.stderr}")
            if not code_prompt:
                return send(f'VS Code aperto su "{project}".')
            vscode_actions.start_claude_code_task(project, path, code_prompt)
            return send(f'VS Code aperto su "{project}". Claude Code al lavoro — ti aggiorno qui appena finisce.')

        if cmd == "/run":
            if not arg:
                return send("Uso: /run <comando>")
            cwd = WORKSPACES.get(state["ws"], JARVIS_HOME)
            result = executor.run(arg, cwd=cwd)
            if result.needs_confirmation:
                return send(f"Serve conferma: /confirm {result.token} oppure /deny {result.token}\nComando: {arg}")
            if result.ok:
                return send(result.stdout.strip() or "(nessun output)")
            return send(f"Errore: {result.stderr}")

        if cmd == "/confirm":
            if not arg:
                return send("Uso: /confirm <token>")
            result = executor.confirm(arg)
            if result.ok:
                return send(result.stdout.strip() or "Eseguito.")
            # Non trovato tra le azioni di SystemExecutor: puo' essere una
            # domanda Genie su PRD in sospeso (/genie_prd) - store separato.
            try:
                answer = await asyncio.to_thread(databricks.confirm_prd, arg)
                return send(f"Genie (PRODUZIONE): {answer}")
            except (databricks.GenieError, databricks.SqlError):
                return send(f"Errore: {result.stderr}")

        if cmd == "/deny":
            if not arg:
                return send("Uso: /deny <token>")
            return send("Annullato." if (executor.deny(arg) or databricks.deny_prd(arg)) else "Token non trovato.")

        if cmd == "/genie_prd":
            if not arg:
                return send("Uso: /genie_prd <domanda>")
            token = databricks.stage_prd_confirmation("genie", arg)
            return send(
                f'Genie su PRODUZIONE (non test): "{arg}"\n'
                f"Confermi? /confirm {token} oppure /deny {token}"
            )

        if cmd == "/sql_prd":
            if not arg:
                return send("Uso: /sql_prd <query SQL, sola lettura>")
            token = databricks.stage_prd_confirmation("sql", arg)
            return send(
                f"Query SQL su PRODUZIONE (non test): {arg}\n"
                f"Confermi? /confirm {token} oppure /deny {token}"
            )

        if cmd == "/voce":
            if arg not in ("on", "off"):
                return send("Uso: /voce on|off")
            state["voice_enabled"] = arg == "on"
            save_state(state)
            return send(f"Voce: {'attiva' if arg == 'on' else 'in pausa'}.")

        if cmd == "/enroll_face":
            from core.voice import face_id  # import qui: opencv/webcam solo se serve

            send("Guardo nella webcam per qualche secondo, resta inquadrato...")
            count, err = await asyncio.to_thread(face_id.capture_and_enroll)
            if err:
                return send(f"Errore: {err}")
            return send(f"Volto appreso ({count} campioni). D'ora in poi ti riconoscero' in camera.")

        return send("Comando sconosciuto. /help")

    # comandi rapidi di sistema (apri/chiudi app, volume, blocco, screenshot,
    # spegni/riavvia) — riconosciuti subito, senza passare da Claude
    intent = intents.parse_intent(text)
    if intent:
        # speak_locally() la legge SEMPRE ad alta voce (anche una nota vocale
        # Telegram trascritta arriva qui come testo normale) — va sempre
        # formattata in "voice" (frasi semplici, italiano pulito), non nel
        # testo tecnico/verboso pensato solo per essere letto (elenchi
        # puntati, messaggi di commit grezzi spesso in inglese). Stesso fix
        # di core/web_bridge.py, stesso motivo (2026-09-15): "perche' parla
        # francese e inglese? ... in linguaggio piu' semplice". "power"
        # resta l'unica eccezione: con voice=True rifiuta del tutto
        # spegnimento/riavvio/logout, romperebbe /confirm per un comando
        # scritto su Telegram.
        voice_flag = intent["type"] != "power"
        # asyncio.to_thread: "stato progetti" arriva fino a ~6 subprocess git in
        # sequenza (~0.2-0.5s l'uno) — troppo per il path pensato per costo/
        # latenza zero, non deve pero' bloccare il polling Telegram nel frattempo.
        response = await asyncio.to_thread(intents.execute_intent, intent, executor, voice_flag, state["ws"], text)
        if intent["type"] != "stop":  # non pronunciare la conferma di "stop" — vedi core/web_bridge.py
            speak_locally(response)
        return send(response)

    # "scatta/fotografa/apri la webcam e dimmi cosa vedi" da Telegram: senza
    # questo Claude non ha modo di ottenere un'immagine vera e finisce per
    # improvvisare (es. aprire un browser). Cattura un frame reale dalla
    # webcam del PC — stesso meccanismo gia' usato dal daemon vocale.
    image_b64 = None
    if camera.wants_camera(text):
        image_b64 = await asyncio.to_thread(camera.capture_frame_b64)

    # "guarda Teams/Outlook/lo schermo/cosa sto facendo su Databricks" -
    # stesso schema della webcam sopra, verso core/screen_context.py.
    # Mutuamente esclusivo con la webcam: una domanda che nomina davvero
    # "webcam/telecamera" resta quella, non ha senso provare entrambe.
    if image_b64 is None:
        screen_target = screen_context.target_for(text)
        if screen_target:
            image_b64 = await screen_context.capture(screen_target)

    # task normale
    typing()
    keepalive = asyncio.create_task(_keepalive())
    try:
        result, _sid, cost = await run_claude(text, image_b64=image_b64)
    finally:
        keepalive.cancel()

    speak_locally(result)
    tail = f"\n\n— {state['ws']} · ${cost:.3f}" if cost else f"\n\n— {state['ws']}"
    send(result + tail)


async def _keepalive() -> None:
    while True:
        await asyncio.sleep(5)
        typing()


# --------------------------------------------------------------------------- loop


async def _transcribe_telegram_voice(file_id: str) -> str:
    """Scarica e trascrive una nota vocale Telegram (OGG/Opus) con lo stesso
    motore whisper gia' usato dal daemon vocale/dashboard (faster-whisper
    via PyAV, decodifica qualunque formato da solo). Nessun filtro parola
    d'attivazione qui a differenza del mic sempre acceso della dashboard:
    mandare una nota vocale e' gia' un'azione esplicita e deliberata,
    stesso principio di scrivere un messaggio di testo normale."""

    def work() -> str:
        import tempfile
        from pathlib import Path

        from core.voice import stt  # import qui: faster-whisper solo se serve davvero

        file_info = requests.get(f"{API}/getFile", params={"file_id": file_id}, timeout=15).json()
        file_path = file_info["result"]["file_path"]
        audio = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=30).content

        fd, tmp_path = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)
        path = Path(tmp_path)
        try:
            path.write_bytes(audio)
            return stt.transcribe_file(str(path))
        finally:
            path.unlink(missing_ok=True)

    return await asyncio.to_thread(work)


async def telegram_loop() -> None:
    send("JARVIS online. /help")
    offset = 0
    while True:
        try:
            r = await asyncio.to_thread(
                lambda: requests.get(
                    f"{API}/getUpdates",
                    params={"offset": offset, "timeout": 50},
                    timeout=60,
                ).json()
            )
        except Exception as e:  # noqa: BLE001
            print("poll error:", e)
            await asyncio.sleep(3)
            continue

        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            if msg["from"]["id"] != OWNER_ID:
                continue
            text = msg.get("text")
            voice = msg.get("voice")
            if not text and not voice:
                continue
            try:
                if voice:
                    text = await _transcribe_telegram_voice(voice["file_id"])
                    if not text:
                        send("Non ho capito niente dalla nota vocale, Signore. Riprova.")
                        continue
                    print(f"> [voce] {text[:80]}")
                else:
                    print(f"> {text[:80]}")
                await handle(text)
            except Exception as e:  # noqa: BLE001
                send(f"Errore: {html.escape(str(e))[:1000]}")


DIGEST_HOUR = int(os.getenv("JARVIS_DAILY_DIGEST_HOUR", "-1"))


async def daily_digest_loop() -> None:
    """Digest mattutino stato progetti su Telegram. Un loop interno invece di
    un secondo task pianificato di Windows: bot.py ora resta sempre acceso
    (avvio automatico), quindi non serve un secondo processo solo per
    l'orario. Disattivo di default (JARVIS_DAILY_DIGEST_HOUR assente/fuori
    range 0-23)."""
    if not 0 <= DIGEST_HOUR <= 23:
        return
    while True:
        now = dt.datetime.now()
        target = now.replace(hour=DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            data = await asyncio.to_thread(briefing.gather_briefing_data, executor)
            send(briefing.format_briefing(data, voice=False))
        except Exception as e:  # noqa: BLE001
            print(f"digest mattutino fallito (ignorato): {e}")


def _push_weather_forecast(data: dict) -> None:
    # Stesso principio del flag "speaking" di core/voice/tts.py: la
    # dashboard (browser) non ha altro modo di conoscere le previsioni,
    # tabella condivisa runtime_flags su Turso.
    turso.execute(
        "CREATE TABLE IF NOT EXISTS runtime_flags ("
        "key TEXT PRIMARY KEY, value TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    turso.execute(
        "INSERT INTO runtime_flags (key, value, updated_at) VALUES ('weather_forecast', ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        [json.dumps(data)],
    )


async def weather_forecast_loop() -> None:
    """Aggiorna le previsioni settimanali su Turso per il pannello meteo
    animato della dashboard (richiesta esplicita di Alessandro, 2026-09-15:
    "come il vero JARVIS di Iron Man"). Il meteo non cambia abbastanza in
    fretta da giustificare piu' di un refresh ogni 30 minuti."""
    if not turso.ENABLED:
        return
    while True:
        try:
            data = await asyncio.to_thread(weather.get_weekly_forecast)
            if data:
                await asyncio.to_thread(_push_weather_forecast, data)
        except Exception as e:  # noqa: BLE001 — un blip di rete non deve mai fermare il loop
            print(f"push previsioni meteo fallito (ignorato): {e}")
        await asyncio.sleep(1800)


def _push_project_status(data: list) -> None:
    turso.execute(
        "CREATE TABLE IF NOT EXISTS runtime_flags ("
        "key TEXT PRIMARY KEY, value TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    turso.execute(
        "INSERT INTO runtime_flags (key, value, updated_at) VALUES ('project_status', ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        [json.dumps(data)],
    )


async def project_status_loop() -> None:
    """Aggiorna lo stato progetti (git + salute) su Turso per il pannello
    "Stato progetti" della dashboard — richiesta esplicita di Alessandro
    (2026-09-15): statistiche vere a schermo, non solo su richiesta
    testuale/vocale. Git status/log e' economico, refresh ogni 10 minuti."""
    if not turso.ENABLED:
        return
    while True:
        try:
            statuses = await asyncio.to_thread(project_status.check_all, executor)
            data = project_status.to_json_ready(statuses)
            await asyncio.to_thread(_push_project_status, data)
        except Exception as e:  # noqa: BLE001
            print(f"push stato progetti fallito (ignorato): {e}")
        await asyncio.sleep(600)


def _push_remote_status(data: dict) -> None:
    turso.execute(
        "CREATE TABLE IF NOT EXISTS runtime_flags ("
        "key TEXT PRIMARY KEY, value TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    turso.execute(
        "INSERT INTO runtime_flags (key, value, updated_at) VALUES ('remote_status', ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        [json.dumps(data)],
    )


async def remote_status_loop() -> None:
    """Aggiorna su Turso lo stato REALE di GitHub/Vercel (non solo i 3
    workspace con path locale di core/project_status.py) — richiesta
    esplicita di Alessandro (2026-09-15): "andrebbe integrato il mio GitHub
    e il mio vercel per vedere tutti i progetti e gli status". Nessuna fretta
    (i deploy non cambiano stato ogni minuto): refresh ogni 15 minuti."""
    if not turso.ENABLED:
        return
    while True:
        try:
            data = await asyncio.to_thread(remote_status.build_remote_status)
            await asyncio.to_thread(_push_remote_status, data)
        except Exception as e:  # noqa: BLE001 — un blip di rete/API non deve mai fermare il loop
            print(f"push stato GitHub/Vercel fallito (ignorato): {e}")
        await asyncio.sleep(900)


CALENDAR_REMINDER_MINUTES = int(os.getenv("JARVIS_CALENDAR_REMINDER_MINUTES", "15") or "15")
_notified_events: dict[str, dt.datetime] = {}


async def calendar_reminder_loop() -> None:
    """Avvisa (Telegram + voce) N minuti prima di ogni meeting Outlook —
    richiesta esplicita di Alessandro (2026-09-16). Stateless tra riavvii
    (_notified_events e' solo in-memory): un restart del bridge puo' far
    ripetere un promemoria gia' mandato pochi minuti prima — rischio
    trascurabile rispetto alla complessita' di persistere lo stato per un
    evento cosi' raro (riavvio + finestra di N minuti)."""
    if CALENDAR_REMINDER_MINUTES <= 0:
        return
    while True:
        try:
            events = await outlook.get_upcoming_events(minutes_ahead=CALENDAR_REMINDER_MINUTES + 5)
            now = dt.datetime.now()
            for ev in events:
                if ev.entry_id in _notified_events:
                    continue
                minutes_to_start = (ev.start - now).total_seconds() / 60
                if 0 <= minutes_to_start <= CALENDAR_REMINDER_MINUTES:
                    send(outlook.format_event_reminder(ev, voice=False))
                    speak_locally(outlook.format_event_reminder(ev, voice=True))
                    _notified_events[ev.entry_id] = now
            # pulizia: dimentica gli eventi ormai notificati da un pezzo,
            # altrimenti il dict cresce senza fine in un processo always-on
            stale = [k for k, notified_at in _notified_events.items() if (now - notified_at).total_seconds() > 3600]
            for k in stale:
                del _notified_events[k]
        except Exception as e:  # noqa: BLE001 — un blip Outlook/COM non deve mai fermare il loop
            print(f"controllo calendario fallito (ignorato): {e}")
        # 120s invece di 60: dimezza quanto spesso questo loop tiene occupato
        # Outlook via COM in background (core/outlook.py::_COM_LOCK serializza
        # comunque ogni accesso, ma un controllo di meno ogni tanto e' un
        # controllo di meno che una domanda vocale reale puo' dover aspettare)
        # — nessuna perdita pratica di precisione sulla finestra di preavviso
        # di N minuti (default 15).
        await asyncio.sleep(120)


def _push_trading_status(data: list) -> None:
    turso.execute(
        "CREATE TABLE IF NOT EXISTS runtime_flags ("
        "key TEXT PRIMARY KEY, value TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    turso.execute(
        "INSERT INTO runtime_flags (key, value, updated_at) VALUES ('trading_status', ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        [json.dumps(data)],
    )


async def trading_snapshot_loop() -> None:
    """Aggiorna su Turso il P&L reale del trading (core/myfxbook.py) per un
    pannello dashboard — richiesta esplicita di Alessandro (2026-09-16,
    dashboard finanziaria: "solo trading per ora", unica fonte dati
    realmente strutturata oggi). Disattivo se Myfxbook non e' configurato
    o il second brain/Turso non e' abilitato. Ogni 15 minuti, stesso ritmo
    di remote_status_loop — i numeri Myfxbook non cambiano piu' in fretta
    di cosi' per uno sguardo d'insieme."""
    if not turso.ENABLED or not myfxbook.ENABLED:
        return
    while True:
        try:
            accounts = await asyncio.to_thread(myfxbook.get_accounts_sync)
            data = [vars(a) for a in accounts]
            await asyncio.to_thread(_push_trading_status, data)
        except Exception as e:  # noqa: BLE001 — un blip Myfxbook non deve mai fermare il loop
            print(f"push stato trading fallito (ignorato): {e}")
        await asyncio.sleep(900)


async def presence_loop() -> None:
    """Presenza proattiva (core/presence.py) — richiesta esplicita di
    Alessandro (2026-09-16). Disattivo di default (JARVIS_PRESENCE_INTERVAL_SEC
    assente/0): attiva la webcam periodicamente senza che lui chieda nulla,
    va acceso di proposito."""
    if not presence.ENABLED:
        return
    tracker = presence.PresenceTracker()
    while True:
        try:
            greeting = await asyncio.to_thread(tracker.check)
            if greeting:
                speak_locally(greeting)
                send(greeting)
        except Exception as e:  # noqa: BLE001 — un blip webcam non deve mai fermare il loop
            print(f"controllo presenza fallito (ignorato): {e}")
        await asyncio.sleep(presence.INTERVAL_SEC)


async def main() -> None:
    tasks = [
        asyncio.create_task(telegram_loop()),
        asyncio.create_task(daily_digest_loop()),
        asyncio.create_task(weather_forecast_loop()),
        asyncio.create_task(project_status_loop()),
        asyncio.create_task(remote_status_loop()),
        asyncio.create_task(calendar_reminder_loop()),
        asyncio.create_task(trading_snapshot_loop()),
        asyncio.create_task(presence_loop()),
    ]
    if web_bridge.ENABLED:
        tasks.append(asyncio.create_task(web_bridge.poll_web_queue()))
    else:
        print("web bridge disabilitato (TURSO_JARVIS_DB_URL/TURSO_JARVIS_AUTH_TOKEN non impostati)")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
