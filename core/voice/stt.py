"""
JARVIS — registrazione + trascrizione locale (faster-whisper), offline.
"""

import os

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from core.voice import resolve_input_device

WHISPER_MODEL_NAME = os.getenv("JARVIS_WHISPER_MODEL", "small")
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280
SILENCE_RMS_THRESHOLD = float(os.getenv("JARVIS_SILENCE_RMS", "300"))


def _positive_int_env(name: str, default: int, minimum: int = 1) -> int:
    """Legge un tuning opzionale senza rendere il daemon indisponibile se
    il .env contiene un valore non numerico."""
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


# La voce viene usata soprattutto per comandi brevi. 1,2 secondi di attesa
# dopo l'ultima parola si sentivano come un ritardo artificiale prima ancora
# della trascrizione; 800 ms lasciano margine per una pausa naturale ma
# accorciano il giro comando -> risposta di ~400 ms. Resta configurabile se
# un microfono/ambiente richiede una soglia più conservativa.
SILENCE_HANG_MS = _positive_int_env("JARVIS_SILENCE_HANG_MS", 800, minimum=300)
MAX_RECORD_SECONDS = 15

# I comandi di JARVIS sono frasi italiane corte: il beam search predefinito
# di Whisper privilegia qualità da dettatura, non il tempo di risposta. Un
# solo candidato riduce il decoding sul fallback CPU senza cambiare modello,
# lingua, VAD o initial prompt. Chi privilegia trascrizioni lunghe può
# riportarlo a 5 dal .env.
WHISPER_BEAM_SIZE = _positive_int_env("JARVIS_WHISPER_BEAM_SIZE", 1)

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    """Prova la GPU (piu' veloce), torna su CPU se CUDA/cuDNN non sono
    disponibili o utilizzabili su questa macchina — mai bloccare l'avvio del
    daemon per questo, e mai far credere che la GPU sia in uso quando in
    realta' e' scattato il fallback."""
    global _model
    if _model is not None:
        return _model
    try:
        _model = WhisperModel(WHISPER_MODEL_NAME, device="cuda", compute_type="float16")
        print("whisper: GPU (CUDA) in uso")
    except Exception as e:  # noqa: BLE001 — qualunque problema CUDA/cuDNN, degrado a CPU
        print(f"whisper: GPU non disponibile ({e}) — uso CPU")
        _model = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def warm_up() -> None:
    """Carica il modello whisper subito, invece che al lazy-load della prima
    trascrizione reale (~30s la prima volta) — altrimenti la primissima
    attivazione dopo un riavvio del daemon sembra "non aver sentito" il
    microfono, quando in realta' sta solo caricando il modello in silenzio."""
    _get_model()


def record_until_silence() -> np.ndarray:
    """Registra dal microfono finché non rileva una pausa di silenzio (o il tetto massimo)."""
    silence_chunks_needed = max(1, int(SILENCE_HANG_MS / (CHUNK_SAMPLES / SAMPLE_RATE * 1000)))
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

    frames: list[np.ndarray] = []
    silence_run = 0
    started_talking = False

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SAMPLES,
        device=resolve_input_device(),
    ) as stream:
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


# "Jarvis" e' un nome inventato: whisper in italiano lo trascrive in modo
# incoerente (verificato dal vivo 2026-09-15 con la stessa identica frase
# sintetizzata: "YARVIS", poi "Giorbis chiarai", a volte lo perde del tutto
# lasciando solo il comando). Un `initial_prompt` che nomina "Jarvis"
# polarizza il decoder verso quella grafia esatta — verificato con lo
# stesso test: risolve la trascrizione errata in tutti i casi provati,
# molto piu' robusto che rincorrere varianti fonetiche via regex lato
# server (core/web_bridge.py::_WAKE_WORD_RE, che resta comunque come rete
# di sicurezza).
_WAKE_WORD_PROMPT = "Jarvis, il maggiordomo AI di Iron Man."


# Verificato dal vivo (2026-09-15) che i log erano pieni di allucinazioni
# di whisper su rumore/silenzio quasi totale — tra cui l'eco letterale
# dell'_WAKE_WORD_PROMPT stesso ("Il maggiordomo AI di Iron Man.") e frasi
# tipiche di allucinazione su silenzio ("Sottotitoli e revisione a cura di
# QTSS", "Buon appetito!"). Riprodotto isolatamente: rumore gaussiano puro
# dato in pasto al modello produce "Buon appetito!" con no_speech_prob=0.90.
# vad_filter=True (silero VAD integrato in faster-whisper) scarta i segmenti
# non vocali PRIMA della decodifica, quindi elimina l'allucinazione alla
# fonte invece di provare a filtrarla dopo per contenuto testuale — stesso
# identico rumore di test con vad_filter=True: trascrizione vuota. Un vero
# comando sintetizzato via TTS resta trascritto correttamente con il filtro
# attivo, quindi non introduce falsi negativi sui comandi reali.
_VAD_PARAMS = {"min_silence_duration_ms": 500}


def transcribe(audio: np.ndarray, language: str = "it") -> str:
    segments, _ = _get_model().transcribe(
        audio, language=language, initial_prompt=_WAKE_WORD_PROMPT,
        vad_filter=True, vad_parameters=_VAD_PARAMS, beam_size=WHISPER_BEAM_SIZE,
        condition_on_previous_text=False,
    )
    return " ".join(s.text for s in segments).strip()


def transcribe_file(path: str, language: str = "it") -> str:
    """Come transcribe(), ma da un file audio su disco (webm/ogg/mp3/wav...)
    invece che da un array registrato dal microfono nativo — usata per
    l'audio caricato dal mic del dashboard web (MediaRecorder del browser,
    non Web Speech API: quest'ultima si e' rivelata irraggiungibile su
    questa rete, vedi memory/log 2026-09-14). faster-whisper decodifica il
    file da solo (via PyAV, gia' una dipendenza) — nessun bisogno di
    convertire prima in PCM."""
    segments, _ = _get_model().transcribe(
        path, language=language, initial_prompt=_WAKE_WORD_PROMPT,
        vad_filter=True, vad_parameters=_VAD_PARAMS, beam_size=WHISPER_BEAM_SIZE,
        condition_on_previous_text=False,
    )
    return " ".join(s.text for s in segments).strip()
