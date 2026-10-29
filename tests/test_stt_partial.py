import io
import wave
from unittest.mock import MagicMock

import numpy as np

from core.voice import stt


def _wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((np.zeros(int(seconds * rate), dtype=np.int16)).tobytes())
    return buf.getvalue()


def test_partial_uses_light_greedy_model_on_last_window(monkeypatch):
    model = MagicMock()
    model.transcribe.return_value = ([MagicMock(text=" apri chrome ")], None)
    monkeypatch.setattr(stt, "_get_partial_model", lambda: model)

    assert stt.transcribe_partial_wav(_wav(12)) == "apri chrome"
    args, kwargs = model.transcribe.call_args
    assert len(args[0]) == stt.PARTIAL_MAX_SECONDS * stt.SAMPLE_RATE  # solo la coda del segmento
    assert kwargs["beam_size"] == 1
    assert kwargs["vad_filter"] is True


def test_partial_does_not_touch_final_model(monkeypatch):
    final = MagicMock()
    partial = MagicMock()
    partial.transcribe.return_value = ([], None)
    monkeypatch.setattr(stt, "_get_model", lambda: final)
    monkeypatch.setattr(stt, "_get_partial_model", lambda: partial)

    stt.transcribe_partial_wav(_wav(1))
    final.transcribe.assert_not_called()


def test_partial_rejects_unsupported_format():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0" * 64)
    try:
        stt.transcribe_partial_wav(buf.getvalue())
    except ValueError:
        return
    raise AssertionError("formato stereo accettato")
