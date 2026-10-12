from unittest.mock import MagicMock

from core.voice import stt


def test_transcribe_uses_low_latency_safe_options(monkeypatch):
    model = MagicMock()
    model.transcribe.return_value = ([MagicMock(text=" apri chrome ")], None)
    monkeypatch.setattr(stt, "_get_model", lambda: model)

    assert stt.transcribe(MagicMock()) == "apri chrome"
    _, kwargs = model.transcribe.call_args
    assert kwargs["vad_filter"] is True
    assert kwargs["beam_size"] == stt.WHISPER_BEAM_SIZE
    assert kwargs["condition_on_previous_text"] is False


def test_positive_int_env_falls_back_for_invalid_value(monkeypatch):
    monkeypatch.setenv("JARVIS_TEST_VALUE", "rapido")

    assert stt._positive_int_env("JARVIS_TEST_VALUE", 800, minimum=300) == 800


def test_transcribe_converts_int16_microphone_audio_to_float32(monkeypatch):
    """record_until_silence() registra int16: il VAD silero di faster-whisper
    accetta solo float32 e falliva con ONNXRuntimeError a ogni hotkey."""
    import numpy as np

    model = MagicMock()
    model.transcribe.return_value = ([], None)
    monkeypatch.setattr(stt, "_get_model", lambda: model)

    stt.transcribe(np.array([0, 16384, -32768], dtype=np.int16))

    sent = model.transcribe.call_args[0][0]
    assert sent.dtype == np.float32
    assert sent.tolist() == [0.0, 0.5, -1.0]
