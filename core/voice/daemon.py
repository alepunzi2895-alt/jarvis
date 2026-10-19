"""
JARVIS — daemon vocale nativo. Processo separato da bot.py.

Wake word -> registra -> trascrive -> esegue -> risponde a voce.
Condivide Engine, memoria e strumenti con la dashboard: API Anthropic
diretta, nessun processo CLI per le normali conversazioni.
Turso mantiene soltanto uno storico delle attivazioni, non una coda.

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

from core import turso, intents, screen_context, telegram, conversation_memory, console_presence
from core.claude_bridge import load_state
from core.executor_singleton import executor
from core.voice import camera, stt, tts, agent
from core.voice.wake_word import WakeWordListener

# Su Windows, stdout/stderr reindirizzati su file usano di default la
# codepage della console (es. cp1252), che non sa codificare em-dash,
# virgolette tipografiche o certi caratteri prodotti dalla trascrizione.
# Senza questo, un print() su quel testo lancia UnicodeEncodeError — preso
# dal try/except del loop, quindi l'intero ciclo falliva in silenzio senza
# rispondere affatto, con zero indizi per l'utente.
# line_buffering=True: senza, un file (non un terminale) usa un buffer a
# blocchi — i print() restano invisibili in logs/voice.log finche' il
# buffer non si riempie o il processo termina (stesso fix applicato a
# bot.py il 2026-09-15, stesso identico problema).
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HOTKEY = os.getenv("JARVIS_HOTKEY", "ctrl+alt+j")
# "console" (default): microfono aperto per la wake word solo con la console
# della dashboard aperta sul PC; la hotkey funziona sempre. "always": come
# prima del 2026-10-15, wake word sempre in ascolto.
WAKE_WORD_MODE = os.getenv("JARVIS_WAKE_WORD_MODE", "console").strip().lower()

# Tetto di sicurezza per il "watcher" che ascolta un'interruzione mentre
# JARVIS parla: la persona vocale è vincolata a risposte brevi (max due
# frasi), quindi il parlato reale dura quasi sempre pochi secondi. Se il
# watcher scade prima che la voce finisca, resta solo un secondo stream
# microfono aperto in più per il tempo restante — nessun effetto collaterale
# oltre a un uso leggermente ridondante del microfono.
INTERRUPT_WATCH_SECONDS = 15


def _wake_word_allowed() -> bool:
    if console_presence.is_open():
        return console_presence.is_mic_enabled()
    return WAKE_WORD_MODE == "always"


def _wait_activation(listener: WakeWordListener, hotkey_pressed: threading.Event) -> bool:
    """True = attivazione (wake word o hotkey). False = la console si e'
    aperta o chiusa: il chiamante ricontrolla e riprova."""
    if _wake_word_allowed():
        return listener.wait(cancel_event=hotkey_pressed, active=_wake_word_allowed)
    # Console chiusa: nessuno stream microfono aperto, solo la hotkey.
    while not hotkey_pressed.wait(timeout=1):
        if _wake_word_allowed():
            return False
    return True


def _voice_enabled() -> bool:
    return load_state().get("voice_enabled", True)


def _current_workspace() -> str:
    return load_state().get("ws", "jarvis")


def _notify_telegram(prompt: str, response: str) -> None:
    """Cosi' puoi rileggere su Telegram anche cio' che dici/senti a voce —
    richiesta esplicita di Alessandro (2026-09-14): non solo ascoltare,
    anche poterlo ritrovare per iscritto. Fire-and-forget in un thread (non
    asyncio.to_thread: qui il ciclo principale e' sincrono, non gira dentro
    un event loop) — core/telegram.py e' condiviso con bot.py apposta,
    invece di duplicare la logica di invio in un secondo processo."""
    text = f'\U0001F3A4 "{prompt}"\n\n{response}'
    threading.Thread(target=telegram.send_to_owner, args=(text,), daemon=True).start()


def _log_task(prompt: str, workspace: str, image_b64: str | None, result: str, cost: float, status: str) -> None:
    """Registra l'interazione in Turso per visibilita' nella dashboard — non
    e' piu' una coda (il lavoro vero e' gia' stato fatto da Engine), solo
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
        if listener.wait(timeout=INTERRUPT_WATCH_SECONDS, cancel_event=stop_watching,
                         active=lambda: _wake_word_allowed() and not stop_watching.is_set()) and not stop_watching.is_set():
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


async def _run_voice_turn(
    engine: tts.TTSEngine, listener: WakeWordListener, prompt: str, workspace: str, image_b64: str | None
) -> tuple[str, float]:
    """Come _speak_with_interrupt(), ma per la risposta streaming: Claude
    genera e JARVIS inizia a parlare dalla prima frase pronta, invece di
    aspettare tutta la risposta (core/voice/agent.py::sentences +
    core/voice/tts.py::speak_stream). Stesso pattern watcher/evento di
    _speak_with_interrupt, solo piu' granulare (l'interruzione puo' fermare
    la voce fra una frase e l'altra, non solo a fine risposta) — la
    generazione/estrazione blocchi (```brain```/```browser```/```system```)
    prosegue comunque fino in fondo anche se l'utente interrompe l'audio."""
    result = agent.VoiceResult()
    stop_watching = threading.Event()
    interrupted = threading.Event()

    def watch() -> None:
        if listener.wait(timeout=INTERRUPT_WATCH_SECONDS, cancel_event=stop_watching,
                         active=lambda: _wake_word_allowed() and not stop_watching.is_set()) and not stop_watching.is_set():
            interrupted.set()
            engine.stop()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        sentences = agent.sentences(prompt, workspace, image_b64, result)
        await engine.speak_stream(sentences, interrupted)
    finally:
        stop_watching.set()
        watcher.join(timeout=2)
    return result.text, result.cost


def main() -> None:
    print("caricamento modelli (whisper, wake word)... qualche secondo, attendere")
    listener = WakeWordListener()
    engine = tts.get_engine()
    stt.warm_up()  # forza il caricamento ora, non alla prima trascrizione reale

    hotkey_pressed = threading.Event()
    keyboard.add_hotkey(HOTKEY, hotkey_pressed.set)
    # Mantiene lo stesso loop per i client async tra i turni vocali.
    voice_loop = asyncio.new_event_loop()
    print(
        f'daemon vocale attivo — di\' "hey jarvis" oppure premi {HOTKEY} '
        f"(modello: {WakeWordListener.__module__}, wake word: {WAKE_WORD_MODE})"
    )

    wake_state = None
    while True:
        try:
            hotkey_pressed.clear()
            allowed = _wake_word_allowed()
            if allowed != wake_state:
                wake_state = allowed
                print("console aperta: wake word in ascolto" if allowed
                      else f"console chiusa: microfono spento, resta {HOTKEY}")
            if not _wait_activation(listener, hotkey_pressed):
                continue

            if not _voice_enabled():
                print("attivazione rilevata ma voce in pausa (/voce off) — ignoro")
                continue

            print("attivazione rilevata (wake word o hotkey), ascolto...")
            manual_activation = hotkey_pressed.is_set()
            audio = stt.record_until_silence(active=lambda: manual_activation or _wake_word_allowed())
            if not manual_activation and not _wake_word_allowed():
                print("microfono disattivato dalla dashboard durante l'ascolto")
                continue
            text = stt.transcribe(audio)
            if not text:
                print("(silenzio, nessun comando)")
                _speak_with_interrupt(engine, listener, "Non ho colto. Me lo ripete?")
                continue
            print(f"> {text}")

            intent = intents.parse_intent(text)
            if intent:
                response = intents.execute_intent(
                    intent, executor, voice=True, workspace=_current_workspace(), raw_text=text
                )
                response = conversation_memory.clean_output(response) or 'Mi concentro sugli altri aspetti.'
                print(f"< {response}")
                _notify_telegram(text, response)
                _speak_with_interrupt(engine, listener, response)
                continue

            image_b64 = None
            if camera.wants_camera(text):
                print("(comando camera rilevato, catturo un frame dalla webcam...)")
                image_b64 = camera.capture_frame_b64()
                if image_b64 is None:
                    print("(webcam non disponibile)")
            else:
                screen_target = screen_context.target_for(text)
                if screen_target:
                    print(f"(comando schermo rilevato: {screen_target}, catturo...)")
                    image_b64 = asyncio.run(screen_context.capture(screen_target))
                    if image_b64 is None:
                        print("(cattura schermo fallita)")

            workspace = _current_workspace()
            cost = 0.0
            status = "done"
            spoken = False  # _run_voice_turn parla gia' in streaming se arriva fin li' senza eccezioni
            try:
                response, cost = voice_loop.run_until_complete(_run_voice_turn(engine, listener, text, workspace, image_b64))
                spoken = True
            except anthropic.AuthenticationError:
                response = (
                    "Chiave API di Anthropic rifiutata. Alessandro deve "
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
                    "Manca la chiave API di Anthropic. Alessandro deve "
                    "impostare ANTHROPIC_API_KEY nel file .env."
                )
                status = "error"
            except anthropic.APIError as e:
                response = f"Errore nel contattare l'API di Claude: {e}"
                status = "error"
            print(f"< {response}")

            _log_task(text, workspace, image_b64, response, cost, status)
            _notify_telegram(text, response)
            if not spoken:
                _speak_with_interrupt(engine, listener, response)
        except Exception as e:  # noqa: BLE001
            # Un daemon di sfondo non deve morire per un errore in un singolo
            # ciclo — si logga e si torna in ascolto.
            print(f"errore nel ciclo vocale (ignorato, resto in ascolto): {e}")


if __name__ == "__main__":
    main()
