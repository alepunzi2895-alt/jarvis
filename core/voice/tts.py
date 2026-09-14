"""
JARVIS — sintesi vocale. Interfaccia comune (`TTSEngine`) + motore di
default gratuito (edge-tts). Un domani un `ElevenLabsEngine` puo'
implementare la stessa interfaccia (speak/stop/speak_stream) senza toccare
core/voice/daemon.py.
"""

import contextlib
import io
import os
import asyncio
import tempfile
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import av
import numpy as np
import sounddevice as sd
import edge_tts

from core.voice import resolve_output_device

VOICE = os.getenv("JARVIS_TTS_VOICE", "it-IT-GiuseppeMultilingualNeural")


class TTSEngine:
    def speak(self, text: str) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    async def speak_stream(self, sentences: AsyncIterator[str], stop_event: threading.Event) -> None:
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
            sd.play(data, samplerate, device=resolve_output_device())
            sd.wait()
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Windows: il file puo' restare bloccato un istante in più

    def stop(self) -> None:
        sd.stop()

    async def speak_stream(self, sentences: AsyncIterator[str], stop_event: threading.Event) -> None:
        """Consuma le frasi generate da claude_api.run_voice_streaming() e le
        parla una per volta, sintetizzando la frase N+1 mentre la N sta
        ancora suonando (coda NON limitata: produttore e consumatore sono
        coroutine indipendenti, il lookahead avviene comunque senza bisogno
        di un limite — un maxsize=1 sembra piu' "naturale" per un lookahead
        di una sola frase, ma puo' restare in deadlock se il consumer esce
        mentre il producer e' bloccato su queue.put(): anche il suo
        `finally: queue.put(None)` si bloccherebbe di nuovo sulla stessa
        coda piena)."""
        queue: asyncio.Queue = asyncio.Queue()

        async def producer() -> None:
            try:
                async for sentence in sentences:
                    if stop_event.is_set():
                        continue  # continua comunque a drenare lo stream: run_voice_streaming deve completare
                    try:
                        audio = await self._synthesize_to_array(sentence)
                    except Exception as e:  # noqa: BLE001 — una frase persa non deve abortire la risposta
                        print(f"(sintesi TTS fallita per una frase, salto: {e})")
                        continue
                    if audio is not None and not stop_event.is_set():
                        await queue.put(audio)
            finally:
                await queue.put(None)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if not stop_event.is_set():
                    data, samplerate = item
                    await asyncio.to_thread(self._play_blocking, data, samplerate, stop_event)
        finally:
            if not producer_task.done():
                producer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer_task  # ripropaga un'eccezione reale del producer (es. errore di autenticazione edge-tts)

    def _play_blocking(self, data: np.ndarray, samplerate: int, stop_event: threading.Event) -> None:
        if stop_event.is_set():
            return
        sd.play(data, samplerate, device=resolve_output_device())
        sd.wait()

    async def _synthesize_to_array(self, text: str) -> tuple[np.ndarray, int] | None:
        text = text.strip()
        if not text:
            return None
        buf = io.BytesIO()
        async for chunk in edge_tts.Communicate(text, VOICE).stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return await asyncio.to_thread(self._decode, buf)

    def _synthesize(self, text: str) -> Path:
        fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        path = Path(tmp_path)

        async def _run():
            await edge_tts.Communicate(text, VOICE).save(str(path))

        asyncio.run(_run())
        return path

    @staticmethod
    def _decode(source: Path | BinaryIO) -> tuple[np.ndarray, int]:
        container = av.open(str(source) if isinstance(source, Path) else source)
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
