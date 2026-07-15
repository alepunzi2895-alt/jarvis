"""
JARVIS — daemon vocale nativo. Processo separato da bot.py.

Wake word -> registra -> trascrive -> esegue -> risponde a voce. Da
2026-07-15 le richieste "vere" (non intercettate da core/intents.py)
passano dall'API Anthropic diretta (core/claude_api.py), NON piu' dalla
coda Turso + claude -p di core/web_bridge.py — scelta esplicita di
Alessandro per abbattere la latenza (niente processo CLI da avviare per
messaggio). Resta comunque una riga per attivazione nella tabella
`tasks` di Turso (stato gia' 'done', mai 'pending') solo per visibilita'
nella dashboard — non e' piu' una coda, e' un log.

Ripetere la wake word MENTRE JARVIS sta parlando interrompe la voce e torna
subito in ascolto di un nuovo comando (niente secondo modello per "stop").
"""

import asyncio
import os
import sys
import threading
import uuid

import anthropic
import keyboard

from core import turso, intents, claude_api
from core.claude_bridge import load_state
from core.executor_singleton import executor
from core.voice import camera, stt, tts
from core.voice.wake_word import WakeWordListener

# Su Windows, stdout/stderr reindirizzati su file usano di default la
# codepage della console (es. cp1252), che non sa codificare em-dash,
# virgolette tipografiche o certi caratteri prodotti dalla trascrizione.
# Senza questo, un print() su quel testo lancia UnicodeEncodeError — preso
# dal try/except del loop, quindi l'intero ciclo falliva in silenzio senza
# rispondere affatto, con zero indizi per l'utente.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOTKEY = os.getenv("JARVIS_HOTKEY", "ctrl+alt+j")

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


def _log_task(prompt: str, workspace: str, image_b64: str | None, result: str, cost: float, status: str) -> None:
    """Registra l'interazione in Turso per visibilita' nella dashboard — non
    e' piu' una coda (il lavoro vero e' gia' stato fatto da claude_api), solo
    uno storico. Se Turso non e' raggiungibile, non blocca la risposta vocale."""
    if not turso.ENABLED:
        return
    try:
        turso.execute(
            "INSERT INTO tasks (id, channel, workspace, prompt, image_b64, status, result, cost_usd) "
            "VALUES (?, 'voice', ?, ?, ?, ?, ?, ?)",
            [str(uuid.uuid4()), workspace, prompt, image_b64, status, result, cost],
        )
    except (OSError, RuntimeError) as e:
        print(f"(log task su Turso fallito, ignorato: {e})")


def _speak_with_interrupt(engine: tts.TTSEngine, listener: WakeWordListener, text: str) -> None:
    stop_watching = threading.Event()

    def watch() -> None:
        if listener.wait(timeout=INTERRUPT_WATCH_SECONDS, cancel_event=stop_watching) and not stop_watching.is_set():
            engine.stop()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    engine.speak(text)
    # Il watcher usa lo stesso WakeWordListener (stesso modello, non
    # thread-safe) del loop principale — va fermato e atteso PRIMA di
    # tornare, altrimenti resta agganciato al microfono fino a
    # INTERRUPT_WATCH_SECONDS mentre il loop prova già ad ascoltare la
    # prossima attivazione, e i due usi concorrenti si bloccano a vicenda.
    stop_watching.set()
    watcher.join(timeout=2)


def main() -> None:
    print("caricamento modelli (whisper, wake word)... qualche secondo, attendere")
    listener = WakeWordListener()
    engine = tts.get_engine()
    stt.warm_up()  # forza il caricamento ora, non alla prima trascrizione reale

    print(
        f'daemon vocale attivo — di\' "hey jarvis" oppure premi {HOTKEY} '
        f"(modello: {WakeWordListener.__module__})"
    )

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

            intent = intents.parse_intent(text)
            if intent:
                response = intents.execute_intent(intent, executor, voice=True)
                print(f"< {response}")
                _speak_with_interrupt(engine, listener, response)
                continue

            image_b64 = None
            if camera.wants_camera(text):
                print("(comando camera rilevato, catturo un frame dalla webcam...)")
                image_b64 = camera.capture_frame_b64()
                if image_b64 is None:
                    print("(webcam non disponibile)")

            workspace = _current_workspace()
            cost = 0.0
            status = "done"
            try:
                response, cost = asyncio.run(claude_api.run_voice(text, workspace, image_b64))
            except anthropic.AuthenticationError:
                response = (
                    "Chiave API di Anthropic rifiutata, Signore. Alessandro deve "
                    "controllare ANTHROPIC_API_KEY nel file .env."
                )
                status = "error"
            except TypeError as e:
                # L'SDK Anthropic solleva un TypeError (non una sua eccezione
                # dedicata) quando non trova NESSUNA credenziale configurata —
                # capita PRIMA di qualunque chiamata di rete, quindi non e'
                # un anthropic.AuthenticationError (quello e' un 401 dal
                # server per una chiave presente ma invalida).
                if "authentic" not in str(e).lower():
                    raise
                response = (
                    "Manca la chiave API di Anthropic, Signore. Alessandro deve "
                    "impostare ANTHROPIC_API_KEY nel file .env."
                )
                status = "error"
            except anthropic.APIError as e:
                response = f"Errore nel contattare l'API di Claude, Signore: {e}"
                status = "error"
            print(f"< {response}")

            _log_task(text, workspace, image_b64, response, cost, status)
            _speak_with_interrupt(engine, listener, response)
        except Exception as e:  # noqa: BLE001
            # Un daemon di sfondo non deve morire per un errore in un singolo
            # ciclo — si logga e si torna in ascolto.
            print(f"errore nel ciclo vocale (ignorato, resto in ascolto): {e}")


if __name__ == "__main__":
    main()
