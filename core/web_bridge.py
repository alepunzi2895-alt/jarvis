"""
JARVIS — poller per la coda task della web dashboard.

Parla direttamente con Turso via HTTP (core/turso.py), NON passa dal gateway
Vercel: su questa rete (GlobalProtect aziendale) le richieste POST verso
*.vercel.app vengono resettate, mentre l'host Turso e' raggiungibile.
Nessuna porta aperta in ingresso: solo richieste outbound, come per Telegram.
"""

import os
import asyncio
import base64
import tempfile
from pathlib import Path

from core import turso, intents, screen_context
from core.claude_bridge import run_claude
from core.executor_singleton import executor
from core.voice import camera, tts

POLL_SEC = float(os.getenv("JARVIS_WEB_POLL_SEC", "3"))

ENABLED = turso.ENABLED


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
    irraggiungibile su questa rete (memory/log 2026-09-14): il browser ora
    registra soltanto (MediaRecorder, gia' verificato funzionante) e manda
    l'audio grezzo qui invece di trascriverlo lui stesso."""

    def work() -> str:
        from core.voice import stt  # import qui: faster-whisper solo se serve davvero

        raw = base64.b64decode(audio_b64)
        fd, tmp_path = tempfile.mkstemp(suffix=".webm")
        os.close(fd)
        path = Path(tmp_path)
        try:
            path.write_bytes(raw)
            return stt.transcribe_file(str(path))
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
                task["prompt"] = text
                await _update_prompt(task["id"], text)

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
            await _push_result(task["id"], "done", result, sid, cost)
        except Exception as e:  # noqa: BLE001
            try:
                await _push_result(task["id"], "error", str(e)[:1500], None, 0.0)
            except Exception as e2:  # noqa: BLE001
                print("web result push error:", e2)
