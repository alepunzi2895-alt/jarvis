"""
JARVIS — core condiviso tra i canali (Telegram, Web): stato, workspace, esecuzione Claude Code.
"""

import os
import json
import time
import base64
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from core import turso, brain, browser, persona

load_dotenv()

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
JARVIS_HOME = Path(os.getenv("JARVIS_HOME", Path(__file__).parent.parent)).resolve()
MAX_TURNS = os.getenv("JARVIS_MAX_TURNS", "40")
MODEL = os.getenv("JARVIS_MODEL", "")  # es. "opus" oppure vuoto = default

STATE_FILE = JARVIS_HOME / "state.json"
TMP_DIR = JARVIS_HOME / ".tmp"

# Workspace = cartelle in cui Jarvis puo' lavorare. Personalizza qui.
WORKSPACES = {
    "jarvis": str(JARVIS_HOME),
    "aura": os.getenv("WS_AURA", str(JARVIS_HOME)),
    "whitesoul": os.getenv("WS_WHITESOUL", str(JARVIS_HOME)),
    "trading": os.getenv("WS_TRADING", str(JARVIS_HOME)),
    "isabela": os.getenv("WS_ISABELA", str(JARVIS_HOME)),
    "vino": os.getenv("WS_VINO", str(JARVIS_HOME)),
}

SYSTEM = (
    "Sei JARVIS, assistente personale di Alessandro. Rivolgiti a lui con "
    "gentilezza e cortesia, sempre — mai freddo, mai sbrigativo. "
    "Rispondi in italiano. Frasi brevi, niente preamboli. "
    "Leggi sempre memory/profile.md e il file di progetto pertinente prima di agire. "
    "A fine task aggiorna memory/log/<data>.md con: task, esito, cosa hai imparato. "
    "Se un task e' distruttivo o irreversibile, chiedi conferma prima.\n\n"
    "Hai anche una memoria a lungo termine (second brain, nodi e relazioni) che ti "
    "viene fornita qui sotto come contesto, quando presente. Quando emerge un'idea, "
    "un fatto o una decisione duratura degna di essere ricordata in futuro (non il "
    "risultato banale di un task qualsiasi), aggiungi IN FONDO alla risposta un blocco:\n"
    "```brain\n"
    '{"nodes":[{"label":"...","summary":"...","tags":["..."]}],'
    '"edges":[{"source":"...","target":"...","relation":"..."}]}\n'
    "```\n"
    "Sii selettivo — non un nodo per ogni risposta. Il blocco viene rimosso prima di "
    "mostrare la risposta, quindi non commentarlo a parole.\n\n"
    "Se l'utente ti chiede di navigare un sito vero, cercare qualcosa e aprirlo, o "
    "guardare un video (non una domanda a cui sai già rispondere), aggiungi IN FONDO "
    "alla risposta un blocco:\n"
    "```browser\n"
    '{"action":"open","url":"..."}\n'
    "```\n"
    "oppure\n"
    "```browser\n"
    '{"action":"search","engine":"youtube","query":"...","open_first_result":true}\n'
    "```\n"
    '("engine" può essere "google" o "youtube"). Usalo solo quando serve davvero '
    "aprire un browser reale — non per domande generiche."
)

# --------------------------------------------------------------------------- state

state: dict = {}
_state_lock = asyncio.Lock()
CLAUDE_LOCK = asyncio.Lock()  # un solo `claude -p` alla volta, condiviso tra tutti i canali


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"ws": "jarvis", "sessions": {}}


def save_state(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, indent=2))


state = load_state()

# --------------------------------------------------------------------------- claude


def _save_temp_image(image_b64: str) -> Path:
    TMP_DIR.mkdir(exist_ok=True)
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    path = TMP_DIR / f"cam-{int(time.time() * 1000)}.jpg"
    path.write_bytes(base64.b64decode(image_b64))
    return path


async def run_claude(
    prompt: str, ws: str | None = None, image_b64: str | None = None, channel: str = "text"
) -> tuple[str, str | None, float]:
    """Lancia claude -p nel workspace indicato (o in quello corrente). Ritorna (testo, session_id, costo)."""
    ws = ws or state["ws"]
    cwd = WORKSPACES.get(ws, str(JARVIS_HOME))
    sid = state["sessions"].get(ws)

    image_path = None
    if image_b64:
        try:
            image_path = await asyncio.to_thread(_save_temp_image, image_b64)
            prompt = (
                f"L'utente ti mostra questa immagine dalla webcam (usa il tuo strumento "
                f"di lettura per vederla): {image_path}\n\n{prompt}"
            )
        except (ValueError, OSError):
            pass  # immagine corrotta: procedi solo col testo

    system_prompt = SYSTEM
    if turso.ENABLED:
        ctx = await asyncio.to_thread(brain.fetch_context, ws)
        if ctx:
            system_prompt = f"{SYSTEM}\n\n{ctx}"
    if channel == "voice":
        system_prompt = f"{system_prompt}\n\n{persona.PERSONA}"

    cmd = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--append-system-prompt",
        system_prompt,
        "--max-turns",
        MAX_TURNS,
        "--permission-mode",
        "acceptEdits",
    ]
    if ws != "trading":
        # I server MCP configurati a livello globale (es. TradingView) si
        # connettono ad ogni avvio anche quando non servono, costando
        # diversi secondi extra per comando. Caricarli solo nel workspace
        # che li usa davvero dimezza il tempo di risposta altrove.
        cmd += ["--strict-mcp-config"]
    if MODEL:
        cmd += ["--model", MODEL]
    if sid:
        cmd += ["--resume", sid]

    async with CLAUDE_LOCK:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()

    try:
        if proc.returncode != 0:
            # sessione corrotta / non trovata -> resetta e riprova pulito
            if sid:
                state["sessions"].pop(ws, None)
                save_state(state)
                return ("Sessione scaduta. Riprova.", None, 0.0)
            return (f"Errore claude:\n{err.decode(errors='replace')[:1500]}", None, 0.0)

        try:
            data = json.loads(out.decode(errors="replace"))
        except json.JSONDecodeError:
            return (out.decode(errors="replace")[:3800], None, 0.0)

        text = data.get("result") or "(nessun output)"
        new_sid = data.get("session_id")
        cost = float(data.get("total_cost_usd") or 0)

        if new_sid:
            state["sessions"][ws] = new_sid
            save_state(state)

        if turso.ENABLED and text:
            text = await asyncio.to_thread(brain.extract_and_store, text, ws)

        if text:
            text = await browser.extract_and_execute(text)

        return (text, new_sid, cost)
    finally:
        if image_path:
            try:
                image_path.unlink(missing_ok=True)
            except OSError:
                pass
