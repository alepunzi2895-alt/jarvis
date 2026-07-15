"""
JARVIS — rilevamento wake word "hey jarvis" (openWakeWord, locale, offline).

Un vero motore di wake-word riconosce il SUONO della frase e attiva
l'ascolto solo dopo averla rilevata acusticamente — non trascrive tutto in
continuo per poi filtrare il testo (a differenza dell'ascolto nel browser,
che ha generato ore di task da rumore ambientale). Modello preaddestrato
ufficiale del progetto openWakeWord, nessun training necessario.
"""

import os
import threading
import time

import sounddevice as sd
from openwakeword.model import Model

from core.voice import resolve_input_device

WAKE_WORD_MODEL = os.getenv("JARVIS_WAKE_WORD_MODEL", "hey_jarvis")
THRESHOLD = float(os.getenv("JARVIS_WAKE_WORD_THRESHOLD", "0.5"))
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280  # 80ms a 16kHz, dimensione raccomandata da openWakeWord


class WakeWordListener:
    def __init__(self):
        self.model = Model(wakeword_models=[WAKE_WORD_MODEL], inference_framework="onnx")

    def wait(self, timeout: float | None = None, cancel_event: threading.Event | None = None) -> bool:
        """Ascolta finché non rileva la wake word, scade il timeout, o scatta
        `cancel_event` (es. una hotkey manuale premuta altrove).

        Ritorna True se rilevata (o se cancel_event è scattato — per chi
        chiama è comunque un "via libera"), False solo per timeout scaduto
        senza rilevamento (con timeout=None blocca finché non succede uno
        dei due).
        """
        detected = threading.Event()

        def callback(indata, frames, time_info, status):
            if detected.is_set():
                return
            score = self.model.predict(indata[:, 0])
            if score.get(WAKE_WORD_MODEL, 0.0) > THRESHOLD:
                detected.set()

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_SAMPLES,
            device=resolve_input_device(),
            callback=callback,
        ):
            if cancel_event is None:
                detected.wait(timeout=timeout)
            else:
                start = time.monotonic()
                while not detected.is_set() and not cancel_event.is_set():
                    if timeout is not None and (time.monotonic() - start) > timeout:
                        break
                    detected.wait(timeout=0.1)

        self.model.reset()
        return detected.is_set() or (cancel_event is not None and cancel_event.is_set())
