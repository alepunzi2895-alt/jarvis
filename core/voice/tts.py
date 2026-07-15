"""
JARVIS — sintesi vocale. Interfaccia comune (`TTSEngine`) + motore di
default gratuito (edge-tts). Un domani un `ElevenLabsEngine` puo'
implementare la stessa interfaccia (speak/stop) senza toccare
core/voice/daemon.py.
"""

import os
import asyncio
import tempfile
from pathlib import Path

import av
import numpy as np
import sounddevice as sd
import edge_tts

VOICE = os.getenv("JARVIS_TTS_VOICE", "it-IT-GiuseppeMultilingualNeural")


class TTSEngine:
    def speak(self, text: str) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class EdgeTTSEngine(TTSEngine):
    """Gratis, nessuna API key. Sintetizza in mp3, decodifica con PyAV
    (già una dipendenza di faster-whisper) e riproduce con sounddevice."""

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        path = self._synthesize(text)
        try:
            data, samplerate = self._decode(path)
            sd.play(data, samplerate)
            sd.wait()
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Windows: il file puo' restare bloccato un istante in più

    def stop(self) -> None:
        sd.stop()

    def _synthesize(self, text: str) -> Path:
        fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        path = Path(tmp_path)

        async def _run():
            await edge_tts.Communicate(text, VOICE).save(str(path))

        asyncio.run(_run())
        return path

    @staticmethod
    def _decode(path: Path) -> tuple[np.ndarray, int]:
        container = av.open(str(path))
        try:
            stream = container.streams.audio[0]
            frames = [f.to_ndarray() for f in container.decode(stream)]
            data = np.concatenate(frames, axis=1).T
            rate = stream.rate
        finally:
            # Su Windows il file va chiuso esplicitamente subito, altrimenti
            # resta bloccato quando si prova a cancellarlo poco dopo.
            container.close()
        return data, rate


def get_engine() -> TTSEngine:
    return EdgeTTSEngine()
