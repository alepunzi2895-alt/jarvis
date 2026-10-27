import asyncio

from core.voice import tts


def test_edge_failure_falls_back_to_windows_voice(monkeypatch):
    async def edge_down(text):
        raise TimeoutError("edge-tts muto")

    calls = []

    def sapi(text):
        calls.append(text)
        return b"RIFF-fake"

    monkeypatch.setattr(tts, "_edge_tts_audio", edge_down)
    monkeypatch.setattr(tts, "_sapi_audio", sapi)
    monkeypatch.setattr(tts, "voice_settings", lambda: {"engine": "edge"})

    assert asyncio.run(tts._tts_audio("Ciao Alessandro.")) == b"RIFF-fake"
    assert calls == ["Ciao Alessandro."]


def test_edge_success_does_not_use_windows_voice(monkeypatch):
    async def edge_ok(text):
        return b"ID3-mp3"

    def sapi(text):
        raise AssertionError("la voce di Windows non deve partire se edge funziona")

    monkeypatch.setattr(tts, "_edge_tts_audio", edge_ok)
    monkeypatch.setattr(tts, "_sapi_audio", sapi)
    monkeypatch.setattr(tts, "voice_settings", lambda: {"engine": "edge"})

    assert asyncio.run(tts._tts_audio("Ciao.")) == b"ID3-mp3"


def test_slow_edge_is_cut_by_timeout(monkeypatch):
    async def edge_slow(text):
        await asyncio.sleep(5)
        return b"ID3-mp3"

    monkeypatch.setattr(tts, "_edge_tts_audio", edge_slow)
    monkeypatch.setattr(tts, "_sapi_audio", lambda text: b"RIFF-fake")
    monkeypatch.setattr(tts, "voice_settings", lambda: {"engine": "edge"})
    monkeypatch.setattr(tts, "EDGE_TTS_TIMEOUT_SEC", 0.05)

    assert asyncio.run(tts._tts_audio("Ciao.")) == b"RIFF-fake"
