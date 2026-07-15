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
from core import web_bridge, intents
from core.executor_singleton import executor, vault

load_dotenv()

TOKEN = os.environ["TELEGRAM_TOKEN"]
OWNER_ID = int(os.environ["TELEGRAM_OWNER_ID"])

API = f"https://api.telegram.org/bot{TOKEN}"

if vault is None:
    print("vault Obsidian non trovato — /note e /search disabilitati")

# --------------------------------------------------------------------------- telegram


def _send_sync(text: str, parse: str | None = None) -> None:
    for chunk in [text[i : i + 3900] for i in range(0, len(text), 3900)] or ["(vuoto)"]:
        payload = {"chat_id": OWNER_ID, "text": chunk, "disable_web_page_preview": True}
        if parse:
            payload["parse_mode"] = parse
        try:
            requests.post(f"{API}/sendMessage", json=payload, timeout=30)
        except Exception as e:  # noqa: BLE001
            print("send error:", e)


def send(text: str, parse: str | None = None) -> None:
    """Fire-and-forget: non blocca il loop asyncio (gira su thread separato)."""
    asyncio.get_running_loop().run_in_executor(None, _send_sync, text, parse)


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


# --------------------------------------------------------------------------- comandi


def cmd_help() -> str:
    return (
        "JARVIS\n\n"
        "Scrivi un task: lo eseguo.\n\n"
        "/ws            workspace attivo\n"
        "/ws <nome>     cambia workspace\n"
        "/new           nuova sessione (dimentica contesto chat)\n"
        "/status        stato\n"
        "/log           log di oggi\n"
        "/note <testo>  scrive nella daily note del vault Obsidian\n"
        "/search <query> cerca nelle note del vault\n"
        "/apri <app>    apre un'applicazione (Chrome, VS Code, Obsidian...)\n"
        "/run <comando> esegue un comando nel workspace attivo (whitelist)\n"
        "/confirm <token> conferma un'azione in sospeso\n"
        "/deny <token>  annulla un'azione in sospeso\n"
        "/voce on|off   attiva/mette in pausa il daemon vocale (hey jarvis)\n"
        "/enroll_face   impara il tuo volto dalla webcam (per il riconoscimento in camera)\n"
        "/help          questo messaggio\n\n"
        "Anche scrivendo normale (senza /) riconosco comandi rapidi come "
        '"apri chrome", "chiudi vs code", "alza il volume", "blocca lo '
        'schermo", "fai uno screenshot", "spegni il pc" — eseguiti subito, '
        "senza passare da Claude.\n\n"
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
            return send(f"Errore: {result.stderr}")

        if cmd == "/deny":
            if not arg:
                return send("Uso: /deny <token>")
            return send("Annullato." if executor.deny(arg) else "Token non trovato.")

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
        return send(intents.execute_intent(intent, executor, voice=False))

    # task normale
    typing()
    keepalive = asyncio.create_task(_keepalive())
    try:
        result, _sid, cost = await run_claude(text)
    finally:
        keepalive.cancel()

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


async def main() -> None:
    tasks = [asyncio.create_task(telegram_loop())]
    if web_bridge.ENABLED:
        tasks.append(asyncio.create_task(web_bridge.poll_web_queue()))
    else:
        print("web bridge disabilitato (TURSO_JARVIS_DB_URL/TURSO_JARVIS_AUTH_TOKEN non impostati)")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
