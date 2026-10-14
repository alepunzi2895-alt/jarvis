"""
JARVIS — server locale XTTS v2 (voce da jarvis_voice/refs).

Gira nel suo ambiente `.venv-xtts` (torch + coqui-tts, incompatibili con le
dipendenze di JARVIS) e tiene il modello caldo in UN solo processo, condiviso
da bot, daemon vocale e LiveBridge: caricarlo in tutti e tre costerebbe ~2 GB
di RAM ciascuno. Ascolta solo su 127.0.0.1.

  GET  /health -> {"ready": bool}
  POST /tts    {"text": "..."} -> audio/wav (PCM 16 bit, 24 kHz, mono)

Avvio: .venv-xtts\\Scripts\\python.exe core\\voice\\xtts_server.py
Modello Coqui XTTS v2: licenza CPML, solo uso non commerciale.
"""
import glob
import io
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REFS = Path(os.getenv("XTTS_REFS_DIR", ROOT / "jarvis_voice" / "refs"))
PORT = int(os.getenv("XTTS_PORT", "8766"))
SR = 24000
MAX_CHARS = 1200
_PAUSE = np.zeros(int(SR * 0.25), dtype=np.float32)

_state = {"model": None, "latents": None}
_lock = threading.Lock()


def _patch_audio_io():
    # Come jarvis_voice/jarvis_tts.py: evita la dipendenza torchcodec.
    try:
        import transformers.utils.import_utils as iu
        iu.is_torchcodec_available = lambda: True
    except Exception:  # noqa: BLE001
        pass
    import torchaudio

    def _load(path, *args, **kwargs):
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), rate

    torchaudio.load = _load


def _latents(model):
    refs = sorted(glob.glob(str(REFS / "*.wav")))
    if not refs:
        raise SystemExit(f"Nessuna clip .wav in {REFS}")
    # Cache su disco: ricalcolarli a ogni avvio costa secondi di CPU.
    stamp = [(Path(r).name, Path(r).stat().st_mtime) for r in refs]
    cache = REFS.parent / "xtts_latents.pt"
    if cache.exists():
        saved = torch.load(cache)
        if saved.get("stamp") == stamp:
            return saved["gpt"], saved["spk"]
    gpt, spk = model.get_conditioning_latents(audio_path=refs)
    torch.save({"stamp": stamp, "gpt": gpt, "spk": spk}, cache)
    return gpt, spk


def load():
    _patch_audio_io()
    from TTS.api import TTS

    started = time.perf_counter()
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
    model = tts.synthesizer.tts_model
    _state["latents"] = _latents(model)
    _state["model"] = model
    print(f"XTTS pronto in {time.perf_counter() - started:.1f}s, thread {torch.get_num_threads()}", flush=True)


def _sentences(text):
    # XTTS in italiano tende a pronunciare il punto finale: frase per frase, senza ".".
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [p.strip().rstrip(".") for p in parts if p.strip().rstrip(".")]


def synthesize(text):
    gpt, spk = _state["latents"]
    chunks = []
    with _lock:  # un'inferenza alla volta: in parallelo si dividerebbero la CPU
        for sentence in _sentences(text):
            out = _state["model"].inference(sentence, "it", gpt, spk, temperature=0.65)
            chunks += [np.asarray(out["wav"], dtype=np.float32), _PAUSE]
    audio = np.concatenate(chunks[:-1]) if chunks else _PAUSE
    buf = io.BytesIO()
    sf.write(buf, audio, SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, body, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._reply(200, json.dumps({"ready": _state["model"] is not None}).encode())
        else:
            self._reply(404, b"{}")

    def do_POST(self):  # noqa: N802
        if self.path != "/tts":
            self._reply(404, b"{}")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            text = json.loads(self.rfile.read(min(length, 64_000)) or b"{}").get("text", "")
        except (ValueError, AttributeError):
            self._reply(400, b'{"error": "json non valido"}')
            return
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS:
            self._reply(400, b'{"error": "testo vuoto o troppo lungo"}')
            return
        if _state["model"] is None:
            self._reply(503, b'{"error": "modello in caricamento"}')
            return
        started = time.perf_counter()
        try:
            audio = synthesize(text)
        except Exception as error:  # noqa: BLE001 — il client ripiega su edge-tts
            print(f"sintesi fallita: {type(error).__name__}: {error}", flush=True)
            self._reply(500, b'{"error": "sintesi fallita"}')
            return
        print(f"{len(text)} caratteri in {time.perf_counter() - started:.1f}s", flush=True)
        self._reply(200, audio, "audio/wav")

    def log_message(self, *args):
        pass  # niente testo delle risposte nei log


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=load, daemon=True).start()
    print(f"XTTS in ascolto su 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
