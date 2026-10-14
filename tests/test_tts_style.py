import asyncio
import io

import numpy as np
from scipy import signal

from core.voice import tts, voice_fx

SR = 24000


def _tone(seconds=0.5, hz=220.0):
    t = np.arange(int(SR * seconds)) / SR
    return 0.5 * np.sin(2 * np.pi * hz * t)


def test_block_filters_match_lfilter():
    x = np.random.default_rng(0).standard_normal(SR)
    for k, g in [(463, 0.55), (98, 0.6), (31, 0.6)]:
        den = np.zeros(k + 1)
        den[0], den[k] = 1, -g
        assert np.allclose(voice_fx._feedback(x, k, g), signal.lfilter([1], den, x))
        num = np.zeros(k + 1)
        num[0], num[k] = -g, 1
        assert np.allclose(voice_fx._allpass(x, k, g), signal.lfilter(num, den, x))


def test_film_keeps_tail_and_limits_peak():
    x = _tone()
    y = voice_fx.film(x, SR)
    assert len(y) == len(x) + int(SR * voice_fx._TAIL_SEC)
    assert np.isfinite(y).all()
    assert 0.8 < np.max(np.abs(y)) <= 0.9
    silent = np.zeros(100)
    assert voice_fx.film(silent, SR) is silent


def test_apply_style_returns_mono_column_or_passthrough(monkeypatch):
    stereo = np.stack([_tone(), _tone()], axis=1).astype(np.float32)
    monkeypatch.setattr(tts, "STYLE", "film")
    out = tts.apply_style(stereo, SR)
    assert out.ndim == 2 and out.shape[1] == 1 and out.dtype == np.float32
    monkeypatch.setattr(tts, "STYLE", "none")
    assert tts.apply_style(stereo, SR) is stereo


def test_edge_tts_receives_voice_rate_and_pitch(monkeypatch):
    seen = {}

    class FakeCommunicate:
        def __init__(self, text, voice, rate, pitch):
            seen.update(text=text, voice=voice, rate=rate, pitch=pitch)

        async def stream(self):
            yield {"type": "audio", "data": b"mp3"}

    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    assert asyncio.run(tts._edge_tts_audio("Ciao")) == b"mp3"
    assert seen == {"text": "Ciao", "voice": tts.VOICE, "rate": tts.RATE, "pitch": tts.PITCH}


def test_synthesize_mp3_applies_style_and_stays_decodable(monkeypatch):
    raw = tts._encode_mp3(_tone(1.0).astype(np.float32)[:, None], SR)

    async def fake_audio(text):
        return raw

    monkeypatch.setattr(tts, "_edge_tts_audio", fake_audio)
    monkeypatch.setattr(tts, "STYLE", "film")
    styled = asyncio.run(tts.synthesize_mp3("Ciao"))
    assert styled != raw
    data, rate = tts.EdgeTTSEngine._decode(io.BytesIO(styled))
    assert rate == SR and data.shape[0] > SR
    monkeypatch.setattr(tts, "STYLE", "none")
    assert asyncio.run(tts.synthesize_mp3("Ciao")) == raw


def test_voice_override_file_applies_without_restart(monkeypatch):
    seen = []

    class FakeCommunicate:
        def __init__(self, text, voice, rate, pitch):
            seen.append((voice, rate, pitch))

        async def stream(self):
            yield {"type": "audio", "data": b"mp3"}

    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    asyncio.run(tts._edge_tts_audio("Ciao"))
    tts.VOICE_OVERRIDE.write_text('{"voice": "it-IT-DiegoNeural", "pitch": "-10Hz", "style": "none"}', encoding="utf-8")
    asyncio.run(tts._edge_tts_audio("Ciao"))
    assert seen == [(tts.VOICE, tts.RATE, tts.PITCH), ("it-IT-DiegoNeural", tts.RATE, "-10Hz")]
    stereo = np.zeros((10, 2), dtype=np.float32)
    assert tts.apply_style(stereo, SR) is stereo
    tts.VOICE_OVERRIDE.write_text("non json", encoding="utf-8")
    import os
    os.utime(tts.VOICE_OVERRIDE, (1, 1))
    assert tts.voice_settings()["voice"] == tts.VOICE
