"""
JARVIS — daemon vocale nativo. Processo separato da bot.py: wake word ->
registra -> trascrive -> esegue (via la STESSA coda Turso di
core/web_bridge.py, non un motore d'esecuzione parallelo) -> risponde a
voce. Comunica con bot.py solo attraverso Turso e state.json, mai in-process.

Ripetere la wake word MENTRE JARVIS sta parlando interrompe la voce e torna
subito in ascolto di un nuovo comando (niente secondo modello per "stop").
"""

import os
import threading
import time
import uuid

import keyboard

from core import turso
from core.claude_bridge import load_state
from core.voice import stt, tts
from core.voice.wake_word import WakeWordListener

HOTKEY = os.getenv("JARVIS_HOTKEY", "ctrl+alt+j")

POLL_SEC = 1.5
MAX_POLL_ATTEMPTS = 120  # ~3 minuti
# Tetto di sicurezza per il "watcher" che ascolta un'interruzione mentre
# JARVIS parla: la persona vocale è vincolata a risposte brevi (max due
# frasi), quindi il parlato reale dura quasi sempre pochi secondi. Se il
# watcher scade prima che la voce finisca, resta solo un secondo stream
# microfono aperto in più per il tempo restante — nessun effetto collaterale
# oltre a un uso leggermente ridondante del microfono.
INTERRUPT_WATCH_SECONDS = 15


def _voice_enabled() -> bool:
    return load_state().get("voice_enabled", True)


def _current_workspace() -> str:
    return load_state().get("ws", "jarvis")


def _push_task(prompt: str, workspace: str) -> str:
    task_id = str(uuid.uuid4())
    turso.execute(
        "INSERT INTO tasks (id, channel, workspace, prompt, status) VALUES (?, 'voice', ?, ?, 'pending')",
        [task_id, workspace, prompt],
    )
    return task_id


def _poll_task(task_id: str) -> dict | None:
    for _ in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_SEC)
        rows = turso.execute("SELECT status, result FROM tasks WHERE id=?", [task_id])
        if rows and rows[0]["status"] in ("done", "error"):
            return rows[0]
    return None


def _speak_with_interrupt(engine: tts.TTSEngine, listener: WakeWordListener, text: str) -> None:
    def watch() -> None:
        if listener.wait(timeout=INTERRUPT_WATCH_SECONDS):
            engine.stop()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    engine.speak(text)


def main() -> None:
    print(
        f'daemon vocale attivo — di\' "hey jarvis" oppure premi {HOTKEY} '
        f"(modello: {WakeWordListener.__module__})"
    )
    listener = WakeWordListener()
    engine = tts.get_engine()

    hotkey_pressed = threading.Event()
    keyboard.add_hotkey(HOTKEY, hotkey_pressed.set)

    while True:
        try:
            hotkey_pressed.clear()
            listener.wait(cancel_event=hotkey_pressed)

            if not _voice_enabled():
                print("attivazione rilevata ma voce in pausa (/voce off) — ignoro")
                continue

            print("attivazione rilevata (wake word o hotkey), ascolto...")
            audio = stt.record_until_silence()
            text = stt.transcribe(audio)
            if not text:
                print("(silenzio, nessun comando)")
                _speak_with_interrupt(engine, listener, "Non ho sentito bene, Signore. Mi ripeta pure.")
                continue
            print(f"> {text}")

            workspace = _current_workspace()
            task_id = _push_task(text, workspace)
            result = _poll_task(task_id)
            response = result["result"] if result else "Timeout, Signore. Nessuna risposta dal bridge locale."
            print(f"< {response}")

            _speak_with_interrupt(engine, listener, response)
        except Exception as e:  # noqa: BLE001
            # Un daemon di sfondo non deve morire per un errore in un singolo
            # ciclo — si logga e si torna in ascolto.
            print(f"errore nel ciclo vocale (ignorato, resto in ascolto): {e}")


if __name__ == "__main__":
    main()
