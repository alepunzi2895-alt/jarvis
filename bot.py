#!/usr/bin/env python3
"""
JARVIS — bridge Telegram <-> Claude Code (headless).
Long polling: nessun tunnel, nessuna porta aperta, nessun URL pubblico.
Gira in parallelo al poller della web dashboard (stesso processo, stesso cervello).
"""

import os
import html
import asyncio
import datetime as dt

import requests
from dotenv import load_dotenv

from core.claude_bridge import (
    WORKSPACES,
    JARVIS_HOME,
    state,
    save_state,
    run_claude,
)
from core import web_bridge, intents, project_status, screen_context, databricks, telegram
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
        "/log           log di oggi\n"
        "/note <testo>  scrive nella daily note del vault Obsidian\n"
        "/search <query> cerca nelle note del vault\n"
        "/apri <app>    apre un'applicazione (Chrome, VS Code, Obsidian...)\n"
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


def cmd_progetti() -> str:
    return project_status.format_report(project_status.check_all(executor), voice=False)


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
        # asyncio.to_thread: "stato progetti" arriva fino a ~6 subprocess git in
        # sequenza (~0.2-0.5s l'uno) — troppo per il path pensato per costo/
        # latenza zero, non deve pero' bloccare il polling Telegram nel frattempo.
        response = await asyncio.to_thread(intents.execute_intent, intent, executor, False, state["ws"], text)
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
            if not text:
                continue
            print(f"> {text[:80]}")
            try:
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
            report = await asyncio.to_thread(cmd_progetti)
            send(f"Buongiorno.\n\n{report}")
        except Exception as e:  # noqa: BLE001
            print(f"digest mattutino fallito (ignorato): {e}")


async def main() -> None:
    tasks = [asyncio.create_task(telegram_loop()), asyncio.create_task(daily_digest_loop())]
    if web_bridge.ENABLED:
        tasks.append(asyncio.create_task(web_bridge.poll_web_queue()))
    else:
        print("web bridge disabilitato (TURSO_JARVIS_DB_URL/TURSO_JARVIS_AUTH_TOKEN non impostati)")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
