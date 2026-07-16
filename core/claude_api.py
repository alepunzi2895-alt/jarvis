"""
JARVIS — canale vocale via API Anthropic diretta, invece del processo CLI
`claude -p` (core/claude_bridge.py). Guadagno di velocita': niente avvio di
un intero processo CLI per messaggio, niente lettura automatica di
CLAUDE.md/memory profile imposta dal progetto (il contesto rilevante e'
gia' iniettato qui sotto), niente riconnessione MCP.

Costo della scelta: nessun accesso reale a strumenti (Read/Write/Bash) —
accettabile perche' la voce e' gia' solo conversazionale (persona breve,
niente task che modificano file). I comandi di sistema restano gestiti
PRIMA di arrivare qui (core/intents.py, per le frasi brevi) o, per
richieste piu' composte, tramite lo stesso blocco ```system```/```browser```
che Claude puo' comunque emettere in testo — nessuno strumento nativo
richiesto, e' pura estrazione di testo (core/system_actions.py,
core/browser.py), quindi funziona identico sia da CLI sia da qui.

Decisione esplicita di Alessandro (2026-07-15): SOLO il canale vocale passa
all'API diretta — Telegram/dashboard restano su claude -p (servono gli
strumenti file/bash per i task reali).

Aggiornamento 2026-07-16 (richiesta esplicita: "ogni interazione e domanda
aggiorna il grafo"): il second brain qui non e' piu' solo in lettura — questo
canale ora estrae e scrive anche i blocchi ```brain``` come claude_bridge.py.
Correggeva anche un bug reale: prima di questo fix, un blocco ```brain```
emesso da Claude durante una risposta vocale (il SYSTEM condiviso lo incoraggia
per qualunque canale, non solo testo) non veniva MAI ripulito qui — sarebbe
finito letto ad alta voce come JSON grezzo dal motore TTS invece di restare
invisibile come sul canale testuale.

Cronologia conversazione: tenuta in memoria di processo (non su
state.json) — la voce e' per natura effimera, e persisterla creerebbe una
corsa tra questo processo e bot.py che scrivono sullo stesso file da
processi diversi. Si azzera ad ogni riavvio del daemon.
"""

from __future__ import annotations

import asyncio
import base64
import os
import threading
from datetime import datetime

import anthropic

from core import browser, persona, system_actions, turso, weather
from core.claude_bridge import SYSTEM
from core.executor_singleton import executor as _system_executor
from core.voice import face_id

MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-4-8",
}


def _resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name)


# Stessa scelta gia' fatta e verificata per la voce via CLI: un modello
# leggero taglia parecchi secondi di latenza, giustificato dal fatto che le
# risposte vocali sono gia' vincolate a poche frasi dalla persona.
MODEL = _resolve_model(os.getenv("JARVIS_VOICE_MODEL", "haiku"))
MAX_TOKENS = int(os.getenv("JARVIS_VOICE_MAX_TOKENS", "1024"))
MAX_HISTORY_MESSAGES = 12  # 6 turni: contesto immediato senza far crescere il costo per sempre

# Prezzi noti (USD per milione di token) - solo per stimare il costo nei log
# allo stesso modo dei task testuali, non e' fatturazione reale.
_PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}

_client: anthropic.AsyncAnthropic | None = None
_history: dict[str, list[dict]] = {}


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


def _estimate_cost(usage) -> float:
    in_price, out_price = _PRICING.get(MODEL, (0.0, 0.0))
    return (usage.input_tokens * in_price + usage.output_tokens * out_price) / 1_000_000


def _decode_b64_image(image_b64: str) -> bytes:
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    return base64.b64decode(image_b64)


def reset_history(ws: str) -> None:
    _history.pop(ws, None)


async def _build_system_prompt(ws: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    system_prompt = f"{SYSTEM}\n\nData e ora attuali: {now}."
    weather_line = await asyncio.to_thread(weather.get_weather_line)
    if weather_line:
        system_prompt += f" Meteo attuale: {weather_line}."
    if turso.ENABLED:
        ctx = await asyncio.to_thread(_fetch_context, ws)
        if ctx:
            system_prompt = f"{system_prompt}\n\n{ctx}"
    return f"{system_prompt}\n\n{persona.PERSONA}"


def _fetch_context(ws: str):
    from core import brain  # import qui: evita di caricare brain.py se turso e' disabilitato

    return brain.fetch_context(ws)


async def run_voice(prompt: str, ws: str, image_b64: str | None = None) -> tuple[str, float]:
    """Chiama l'API Anthropic direttamente (nessun processo CLI). Ritorna
    (testo, costo_stimato)."""
    client = _get_client()
    system_prompt = await _build_system_prompt(ws)

    user_text = prompt
    content: str | list[dict]
    if image_b64:
        raw = _decode_b64_image(image_b64)
        try:
            import numpy as np
            import cv2

            frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            name, _confidence = face_id.recognize(frame) if frame is not None else (None, -1.0)
            if name:
                user_text = (
                    f"Riconoscimento locale (webcam): la persona nella foto e' quasi "
                    f"certamente {name.capitalize()} — puoi rivolgerti a lui per nome se "
                    f"ha senso.\n\n{prompt}"
                )
        except Exception:
            pass  # riconoscimento best-effort: se fallisce si procede senza identita'

        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode("ascii")},
            },
            {
                "type": "text",
                "text": (
                    "L'utente ti mostra questa immagine dalla webcam. Se indossa degli "
                    "occhiali, commenta scherzosamente (una battuta breve, non seriosa) "
                    "che con quegli occhiali sembra napoletano — solo se ci sono davvero "
                    f"occhiali visibili, altrimenti non nominarlo.\n\n{user_text}"
                ),
            },
        ]
    else:
        content = user_text

    history = _history.get(ws, [])
    messages = [*history, {"role": "user", "content": content}]

    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )
    text = next((b.text for b in response.content if b.type == "text"), "") or "(nessun output)"

    if turso.ENABLED:
        from core import brain  # import qui: evita di caricare brain.py se turso e' disabilitato

        text = await asyncio.to_thread(brain.extract_and_store, text, ws)
        # Fire-and-forget (thread, non asyncio.to_thread): questa funzione e'
        # spesso invocata via asyncio.run() per singola chiamata
        # (core/voice/daemon.py) — un task asyncio non atteso verrebbe
        # cancellato alla chiusura del loop prima di completare, un thread no.
        threading.Thread(target=brain.log_interaction, args=(prompt, ws, "voice"), daemon=True).start()

    text = await browser.extract_and_execute(text)
    text = await system_actions.extract_and_execute(text, _system_executor)

    new_history = [*history, {"role": "user", "content": prompt}, {"role": "assistant", "content": text}]
    _history[ws] = new_history[-MAX_HISTORY_MESSAGES:]

    return text, _estimate_cost(response.usage)
