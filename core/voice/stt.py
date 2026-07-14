"""
JARVIS — registrazione + trascrizione locale (faster-whisper), offline.
"""

import os

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

WHISPER_MODEL_NAME = os.getenv("JARVIS_WHISPER_MODEL", "small")
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280
SILENCE_RMS_THRESHOLD = float(os.getenv("JARVIS_SILENCE_RMS", "300"))
SILENCE_HANG_MS = 1200  # pausa di silenzio che conclude la frase
MAX_RECORD_SECONDS = 15

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def record_until_silence() -> np.ndarray:
    """Registra dal microfono finché non rileva una pausa di silenzio (o il tetto massimo)."""
    silence_chunks_needed = max(1, int(SILENCE_HANG_MS / (CHUNK_SAMPLES / SAMPLE_RATE * 1000)))
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

    frames: list[np.ndarray] = []
    silence_run = 0
    started_talking = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=CHUNK_SAMPLES) as stream:
        for _ in range(max_chunks):
            chunk, _ = stream.read(CHUNK_SAMPLES)
            frames.append(chunk.copy())
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            if rms > SILENCE_RMS_THRESHOLD:
                started_talking = True
                silence_run = 0
            elif started_talking:
                silence_run += 1
                if silence_run >= silence_chunks_needed:
                    break

    return np.concatenate(frames, axis=0).flatten()


def transcribe(audio: np.ndarray, language: str = "it") -> str:
    segments, _ = _get_model().transcribe(audio, language=language)
    return " ".join(s.text for s in segments).strip()
