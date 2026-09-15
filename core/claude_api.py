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
strumenti file/bash per i task reali). **Aggiornamento 2026-09-15**: anche
testo/Telegram/dashboard sono passati all'API diretta (motore di default in
`core/claude_bridge.py::_run_claude_api()`), ma con Read/Write/Bash reali
ricostruiti come tool appoggiati a `core/system_executor.py::SystemExecutor`
(whitelist + conferma gia' esistenti) — non piu' "nessun accesso reale a
strumenti" per quel canale. Questo modulo (voce) resta com'era: nessun tool
reale, persona breve, conversazionale.

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
import re
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import anthropic

from core import browser, databricks, persona, system_actions, turso, weather
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
    # In parallelo, non in sequenza (stesso fix di core/claude_bridge.py):
    # sono due chiamate di rete indipendenti prima di rispondere a voce,
    # dove ogni secondo si sente.
    weather_task = asyncio.create_task(asyncio.to_thread(weather.get_weather_line))
    brain_task = asyncio.create_task(asyncio.to_thread(_fetch_context, ws)) if turso.ENABLED else None
    weather_line = await weather_task
    if weather_line:
        system_prompt += f" Meteo attuale: {weather_line}."
    if brain_task:
        ctx = await brain_task
        if ctx:
            system_prompt = f"{system_prompt}\n\n{ctx}"
    return f"{system_prompt}\n\n{persona.PERSONA}"


def _fetch_context(ws: str):
    from core import brain  # import qui: evita di caricare brain.py se turso e' disabilitato

    return brain.fetch_context(ws)


@dataclass
class VoiceStreamResult:
    """Raccoglie l'esito di run_voice_streaming() — un generator puo' fare
    yield di frasi ma non anche return-are (testo, costo) al chiamante,
    quindi li scrive qui mano a mano che diventano noti."""

    text: str = ""
    cost: float = 0.0


# Confine di frase: spazio/newline che segue .!? — lookbehind, cosi' lo
# spazio stesso non finisce ne' nella frase completata ne' nel frammento
# successivo. Nessuna libreria di sentence-splitting nel repo: per frasi
# corte (persona vocale) un regex semplice basta, non serve NLTK/spaCy.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_FENCE = "```"


def _split_sentences(buf: str) -> tuple[list[str], str]:
    """Frasi complete + un frammento finale (senza terminatore certo, quindi
    potenzialmente ancora incompleto) che resta accumulato per il prossimo
    pezzo di stream."""
    parts = _SENTENCE_SPLIT_RE.split(buf)
    return parts[:-1], parts[-1]


async def _build_messages(prompt: str, ws: str, image_b64: str | None) -> tuple[str, list[dict], list[dict]]:
    """Fattorizza la costruzione di system prompt/content/messages, condivisa
    da run_voice_streaming() — l'unica differenza fra le due era la chiamata
    finale (create() vs stream()), non la preparazione della richiesta."""
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
    return system_prompt, history, messages


async def run_voice_streaming(
    prompt: str, ws: str, image_b64: str | None, result: VoiceStreamResult
) -> AsyncIterator[str]:
    """Come run_voice(), ma genera (yield) le frasi della risposta mano a
    mano che Claude le completa, invece di aspettare tutta la risposta —
    core/voice/tts.py::speak_stream() le sintetizza/parla una per volta.
    Testo/costo finali (identici a quello che tornava run_voice()) finiscono
    in `result`.

    Sicurezza: il SYSTEM prompt condiviso istruisce Claude a mettere i
    blocchi ```brain```/```browser```/```system``` IN FONDO alla risposta —
    appena compare un fence ``` nel testo non ancora pronunciato si smette
    di generare frasi da parlare (fence_seen=True), ma l'accumulo del testo
    completo per l'estrazione blocchi prosegue invariato, identico a prima.
    Mai il rischio di far leggere JSON grezzo dal TTS (bug reale gia'
    successo una volta — vedi la cronologia in cima al modulo)."""
    client = _get_client()
    system_prompt, history, messages = await _build_messages(prompt, ws, image_b64)

    full_text = ""
    buf = ""
    fence_seen = False
    usage = None

    async with client.messages.stream(
        model=MODEL, max_tokens=MAX_TOKENS, system=system_prompt, messages=messages
    ) as stream:
        async for delta in stream.text_stream:
            full_text += delta
            if fence_seen:
                continue
            buf += delta
            fence_idx = buf.find(_FENCE)
            if fence_idx != -1:
                pre, buf, fence_seen = buf[:fence_idx], "", True
                complete, _leftover = _split_sentences(pre)  # frammento prima del fence: scartato, mai pronunciato
                for s in complete:
                    if s.strip():
                        yield s.strip()
                continue
            complete, buf = _split_sentences(buf)
            for s in complete:
                if s.strip():
                    yield s.strip()
        if not fence_seen and buf.strip():
            yield buf.strip()
        final_message = await stream.get_final_message()
        usage = final_message.usage

    text = full_text or "(nessun output)"

    if turso.ENABLED:
        from core import brain  # import qui: evita di caricare brain.py se turso e' disabilitato

        text = await asyncio.to_thread(brain.extract_and_store, text, ws)
        # Fire-and-forget (thread, non asyncio.to_thread): questa funzione e'
        # spesso invocata via asyncio.run() per singola chiamata
        # (core/voice/daemon.py) — un task asyncio non atteso verrebbe
        # cancellato alla chiusura del loop prima di completare, un thread no.
        threading.Thread(target=brain.log_interaction, args=(prompt, ws, "voice"), daemon=True).start()

    text = await browser.extract_and_execute(text)
    text = await databricks.extract_and_execute(text)
    text = await system_actions.extract_and_execute(text, _system_executor)

    new_history = [*history, {"role": "user", "content": prompt}, {"role": "assistant", "content": text}]
    _history[ws] = new_history[-MAX_HISTORY_MESSAGES:]

    result.text = text
    result.cost = _estimate_cost(usage) if usage else 0.0


async def run_voice(prompt: str, ws: str, image_b64: str | None = None) -> tuple[str, float]:
    """Chiama l'API Anthropic direttamente (nessun processo CLI). Ritorna
    (testo, costo_stimato) — wrapper sottile su run_voice_streaming() per chi
    non ha bisogno dell'audio incrementale (es. i test)."""
    result = VoiceStreamResult()
    async for _ in run_voice_streaming(prompt, ws, image_b64, result):
        pass
    return result.text, result.cost
