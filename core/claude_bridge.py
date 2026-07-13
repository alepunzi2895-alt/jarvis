"""
JARVIS — core condiviso tra i canali (Telegram, Web): stato, workspace, esecuzione Claude Code.
"""

import os
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
JARVIS_HOME = Path(os.getenv("JARVIS_HOME", Path(__file__).parent.parent)).resolve()
MAX_TURNS = os.getenv("JARVIS_MAX_TURNS", "40")
MODEL = os.getenv("JARVIS_MODEL", "")  # es. "opus" oppure vuoto = default

STATE_FILE = JARVIS_HOME / "state.json"

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
    "Sei JARVIS, assistente personale di Alessandro. "
    "Rispondi in italiano. Frasi brevi, niente preamboli. "
    "Leggi sempre memory/profile.md e il file di progetto pertinente prima di agire. "
    "A fine task aggiorna memory/log/<data>.md con: task, esito, cosa hai imparato. "
    "Se un task e' distruttivo o irreversibile, chiedi conferma prima."
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


async def run_claude(prompt: str, ws: str | None = None) -> tuple[str, str | None, float]:
    """Lancia claude -p nel workspace indicato (o in quello corrente). Ritorna (testo, session_id, costo)."""
    ws = ws or state["ws"]
    cwd = WORKSPACES.get(ws, str(JARVIS_HOME))
    sid = state["sessions"].get(ws)

    cmd = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--append-system-prompt",
        SYSTEM,
        "--max-turns",
        MAX_TURNS,
        "--permission-mode",
        "acceptEdits",
    ]
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

    return (text, new_sid, cost)
