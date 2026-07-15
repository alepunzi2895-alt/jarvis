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

    def wait(self, timeout: float | None = None) -> bool:
        """Ascolta finché non rileva la wake word o scade il timeout.

        Ritorna True se rilevata, False se e' scaduto il timeout (con
        timeout=None blocca indefinitamente e ritorna sempre True).
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
            detected.wait(timeout=timeout)

        self.model.reset()
        return detected.is_set()
