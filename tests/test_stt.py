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
