"""
JARVIS — poller per la coda task della web dashboard.

Parla direttamente con Turso via HTTP (core/turso.py), NON passa dal gateway
Vercel: su questa rete (GlobalProtect aziendale) le richieste POST verso
*.vercel.app vengono resettate, mentre l'host Turso e' raggiungibile.
Nessuna porta aperta in ingresso: solo richieste outbound, come per Telegram.
"""

import os
import re
import asyncio
import base64
import tempfile
from pathlib import Path

from core import turso, intents, screen_context, telegram
from core.claude_bridge import run_claude
from core.executor_singleton import executor
from core.voice import camera, tts

POLL_SEC = float(os.getenv("JARVIS_WEB_POLL_SEC", "3"))

ENABLED = turso.ENABLED

# Il mic della dashboard ora ascolta a mani libere in continuo (mai un
# click per singolo comando) — senza questo filtro trascriverebbe e
# sottoporrebbe come task reale qualunque rumore ambientale captato dal
# rilevatore di silenzio lato browser (TV, conversazioni). Stesso problema e
# stessa soluzione gia' visti una volta con l'ascolto continuo del vecchio
# riconoscimento cloud del browser (2026-07-14: ~230 task spuri, ~1.33$ di
# chiamate Claude vere prima che esistesse un filtro equivalente) — qui il
# filtro vive lato server perche' la trascrizione stessa (faster-whisper)
# avviene qui, non piu' nel browser.
#
# Non solo "jarvis" esatto: verificato dal vivo (2026-09-15, sintesi vocale
# di prova) che whisper in italiano puo' trascrivere foneticamente "Jarvis"
# in modi diversi ("YARVIS" osservato) — un match troppo rigido avrebbe
# scartato in silenzio comandi veri e propri. "arvis" resta il nucleo
# fonetico comune a tutte le varianti plausibili.
_WAKE_WORD_RE = re.compile(r"\b(?:j|gi|y|sci|sh)?arvis\b", re.IGNORECASE)
_NOISE_WORDS = {"oh", "ah", "eh", "ehi", "ehm", "uhm", "mh", "boh"}

# Frasi di allucinazione note di whisper su audio quasi silenzioso/rumore
# (osservate ripetutamente nei log reali del 2026-09-15, riprodotte anche
# isolatamente dando in pasto al modello rumore gaussiano puro) — incluso
# l'eco letterale dell'initial_prompt usato in core/voice/stt.py. Scartate
# a prescindere dalla wake word: sono garbage, non comandi, anche se per
# puro caso contenessero "arvis". vad_filter in stt.py e' il fix principale
# (elimina l'allucinazione alla fonte), questo resta una seconda rete di
# sicurezza indipendente dal motore di trascrizione.
_HALLUCINATION_PHRASES = {
    "il maggiordomo ai di iron man",
    "sottotitoli e revisione a cura di qtss",
    "buon appetito",
    "grazie",
    "sì sì",
    "si si",
}

# La wake word deve comparire vicino all'inizio dell'enunciato ("Jarvis,
# ..."/"Ok Jarvis..."), non in un punto qualunque di una frase lunga —
# altrimenti un'allucinazione/rumore di sottofondo che nomina "arvis" a
# meta' frase (es. dentro un discorso captato per sbaglio) verrebbe presa
# per un comando reale. 24 caratteri copre comodamente "ehi jarvis"/
# "ok jarvis"/"ciao jarvis" piu' un margine.
_WAKE_WORD_MAX_START = 24


def _strip_wake_word(text: str) -> str | None:
    """None se manca la parola d'attivazione vicino all'inizio (o resta
    solo rumore/allucinazione nota) — altrimenti il comando vero e proprio,
    ripulito."""
    normalized = text.strip().lower().strip(" ,.!?\t\n")
    if normalized in _HALLUCINATION_PHRASES:
        return None
    match = _WAKE_WORD_RE.search(text)
    if not match or match.start() > _WAKE_WORD_MAX_START:
        return None
    command = text[match.end():].strip(" ,.\t\n")
    if len(command) < 4 or command.lower() in _NOISE_WORDS:
        return None
    return command


async def _claim_next_task() -> dict | None:
    def work():
        rows = turso.execute(
            "SELECT id, channel, workspace, prompt, image_b64, audio_b64 FROM tasks "
            "WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
        )
        if not rows:
            return None
        task = rows[0]
        turso.execute(
            "UPDATE tasks SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [task["id"]],
        )
        return task

    return await asyncio.to_thread(work)


async def _transcribe_audio(audio_b64: str) -> str:
    """Trascrive in locale (faster-whisper, stesso motore del daemon vocale
    nativo) l'audio registrato dal microfono del dashboard — il
    riconoscimento cloud del browser (Web Speech API/Google) si e' rivelato
    irraggiungibile su questa rete (memory/log 2026-09-14). Il browser cattura
    PCM grezzo con AudioContext/ScriptProcessorNode e incapsula un WAV al volo
    (non piu' MediaRecorder/webm dal 2026-09-15 — la cattura per segmenti
    real-time a mani libere aveva bisogno di un pre-buffer prima del
    rilevamento voce, impossibile da ottenere pulito ricreando un MediaRecorder
    ad ogni segmento; il WAV toglie anche l'ambiguita' di formato lato server)."""

    def work() -> str:
        import wave

        from core.voice import stt  # import qui: faster-whisper solo se serve davvero

        raw = base64.b64decode(audio_b64)
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        path = Path(tmp_path)
        try:
            path.write_bytes(raw)
            try:
                with wave.open(str(path), "rb") as w:
                    duration_ms = (w.getnframes() / w.getframerate()) * 1000
            except Exception as e:  # noqa: BLE001 — solo diagnostica, non deve bloccare la trascrizione vera
                duration_ms = None
                print(f"[web audio] WAV non leggibile con wave.open: {e}")
            text = stt.transcribe_file(str(path))
            # Diagnostica temporanea (2026-09-15): il mic dashboard ha appena
            # avuto un giro di fix per trascrizioni vuote — utile vedere
            # dimensione/durata reali finche' non e' confermato risolto dal vivo.
            dur = f"{duration_ms:.0f}ms" if duration_ms is not None else "?"
            print(f"[web audio] {len(raw)} bytes, {dur} -> trascritto: {text!r}")
            return text
        finally:
            path.unlink(missing_ok=True)

    return await asyncio.to_thread(work)


async def _update_prompt(task_id: str, prompt: str) -> None:
    """Scrive la trascrizione nella riga (channel->'web', come un task
    testuale normale) cosi' la dashboard, che sta gia' facendo polling su
    questo task, mostra subito "hai detto: ..." invece di restare sul
    placeholder mentre Claude elabora la risposta vera."""

    def work():
        turso.execute(
            "UPDATE tasks SET prompt=?, channel='web', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [prompt, task_id],
        )

    await asyncio.to_thread(work)


def _notify_telegram(prompt: str, response: str) -> None:
    """Specchia su Telegram anche l'esito della dashboard — richiesta
    esplicita di Alessandro, stesso schema gia' usato per la voce
    (core/voice/daemon.py::_notify_telegram). Fire-and-forget in un thread
    dell'executor, non deve mai rallentare il poller."""

    def work() -> None:
        text = f'\U0001F4BB "{prompt}"\n\n{response}'
        telegram.send_to_owner(text)

    asyncio.get_running_loop().run_in_executor(None, work)


async def _push_result(task_id: str, status: str, result: str, session_id: str | None, cost_usd: float) -> None:
    def work():
        turso.execute(
            "UPDATE tasks SET status=?, result=?, session_id=?, cost_usd=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [status, result, session_id, cost_usd, task_id],
        )

    await asyncio.to_thread(work)


async def poll_web_queue() -> None:
    print(f"web bridge attivo -> Turso {turso.DB_URL}")
    while True:
        try:
            task = await _claim_next_task()
        except (OSError, RuntimeError) as e:
            print("web poll error:", e)
            await asyncio.sleep(POLL_SEC)
            continue

        if not task:
            await asyncio.sleep(POLL_SEC)
            continue

        try:
            audio_b64 = task.get("audio_b64")
            if audio_b64:
                text = await _transcribe_audio(audio_b64)
                if not text:
                    await _push_result(task["id"], "error", "Non ho capito niente dall'audio, Signore. Riprova.", None, 0.0)
                    continue
                await _update_prompt(task["id"], text)  # mostra sempre cosa ha sentito, anche se poi lo ignora

                command = _strip_wake_word(text)
                if command is None:
                    await _push_result(task["id"], "ignored", "", None, 0.0)
                    continue
                task["prompt"] = command

            print(f"> [web] {task['prompt'][:80]}")
            image_b64 = task.get("image_b64")

            intent = intents.parse_intent(task["prompt"]) if not image_b64 else None
            if intent:
                # asyncio.to_thread: "stato progetti" arriva fino a ~6 subprocess
                # git in sequenza — non deve bloccare il polling della coda.
                response = await asyncio.to_thread(
                    intents.execute_intent,
                    intent, executor, False, task.get("workspace") or "jarvis", task["prompt"],
                )
                tts.speak_if_enabled(response)
                _notify_telegram(task["prompt"], response)
                await _push_result(task["id"], "done", response, None, 0.0)
                continue

            # Se il client (dashboard) non ha gia' allegato un'immagine (es.
            # dal pannello camera con getUserMedia) e il testo chiede
            # esplicitamente di vedere/scattare, cattura un frame reale dalla
            # webcam del PC — altrimenti Claude non ha modo di "vedere" e
            # improvvisa (es. aprendo un browser verso la dashboard stessa).
            if not image_b64 and camera.wants_camera(task["prompt"]):
                image_b64 = await asyncio.to_thread(camera.capture_frame_b64)
            if not image_b64:
                screen_target = screen_context.target_for(task["prompt"])
                if screen_target:
                    image_b64 = await screen_context.capture(screen_target)

            result, sid, cost = await run_claude(
                task["prompt"],
                ws=task.get("workspace"),
                image_b64=image_b64,
                channel=task.get("channel") or "text",
            )
            tts.speak_if_enabled(result)
            _notify_telegram(task["prompt"], result)
            await _push_result(task["id"], "done", result, sid, cost)
        except Exception as e:  # noqa: BLE001
            try:
                await _push_result(task["id"], "error", str(e)[:1500], None, 0.0)
            except Exception as e2:  # noqa: BLE001
                print("web result push error:", e2)
