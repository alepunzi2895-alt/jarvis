import asyncio

import pytest

from core.voice import tts


def _edge_down_twice_then(monkeypatch, sapi_enabled):
    calls, sapi_calls = [], []

    async def edge_down(text):
        calls.append(text)
        raise TimeoutError("edge-tts muto")

    def sapi(text):
        sapi_calls.append(text)
        return b"RIFF-fake"

    monkeypatch.setattr(tts, "_edge_tts_audio", edge_down)
    monkeypatch.setattr(tts, "_sapi_audio", sapi)
    monkeypatch.setattr(tts, "voice_settings", lambda: {"engine": "edge"})
    monkeypatch.setattr(tts, "SAPI_FALLBACK", sapi_enabled)
    return calls, sapi_calls


def test_edge_failure_keeps_same_voice_by_default(monkeypatch):
    """2026-10-28: la voce di Windows a meta' risposta suonava come un'altra persona."""
    calls, sapi_calls = _edge_down_twice_then(monkeypatch, sapi_enabled=False)
    with pytest.raises(TimeoutError):
        asyncio.run(tts._tts_audio("Ciao Alessandro."))
    assert calls == ["Ciao Alessandro."] * 2  # un secondo tentativo con edge-tts
    assert sapi_calls == []


def test_windows_voice_only_when_enabled(monkeypatch):
    calls, sapi_calls = _edge_down_twice_then(monkeypatch, sapi_enabled=True)
    assert asyncio.run(tts._tts_audio("Ciao Alessandro.")) == b"RIFF-fake"
    assert sapi_calls == ["Ciao Alessandro."]


def test_edge_success_does_not_use_windows_voice(monkeypatch):
    async def edge_ok(text):
        return b"ID3-mp3"

    def sapi(text):
        raise AssertionError("la voce di Windows non deve partire se edge funziona")

    monkeypatch.setattr(tts, "_edge_tts_audio", edge_ok)
    monkeypatch.setattr(tts, "_sapi_audio", sapi)
    monkeypatch.setattr(tts, "voice_settings", lambda: {"engine": "edge"})

    assert asyncio.run(tts._tts_audio("Ciao.")) == b"ID3-mp3"


def test_long_text_gets_longer_timeout_and_slow_edge_is_retried(monkeypatch):
    attempts = []

    async def edge_slow_first(text):
        attempts.append(text)
        if len(attempts) == 1:
            await asyncio.sleep(5)
        return b"ID3-mp3"

    monkeypatch.setattr(tts, "_edge_tts_audio", edge_slow_first)
    monkeypatch.setattr(tts, "voice_settings", lambda: {"engine": "edge"})
    monkeypatch.setattr(tts, "EDGE_TTS_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(tts, "EDGE_TTS_SEC_PER_CHAR", 0.0)

    assert asyncio.run(tts._tts_audio("Ciao.")) == b"ID3-mp3"
    assert len(attempts) == 2
