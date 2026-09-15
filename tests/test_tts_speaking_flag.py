import asyncio
import threading

from core.voice import tts


def test_set_speaking_noop_when_turso_disabled(monkeypatch):
    monkeypatch.setattr(tts.turso, "ENABLED", False)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda *a, **k: calls.append((a, k)))
    tts._set_speaking(True)
    assert calls == []


def test_set_speaking_writes_upsert_when_enabled(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", True)  # salta il CREATE TABLE
    monkeypatch.setattr(tts.turso, "ENABLED", True)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda sql, args=None: calls.append((sql, args)))

    tts._set_speaking(True)

    assert len(calls) == 1
    sql, args = calls[0]
    assert "runtime_flags" in sql
    assert "ON CONFLICT" in sql
    assert args == ["1"]


def test_set_speaking_false_writes_zero(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", True)
    monkeypatch.setattr(tts.turso, "ENABLED", True)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda sql, args=None: calls.append(args))

    tts._set_speaking(False)

    assert calls == [["0"]]


def test_set_speaking_swallows_turso_errors(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", True)
    monkeypatch.setattr(tts.turso, "ENABLED", True)

    def _boom(sql, args=None):
        raise RuntimeError("rete giu'")

    monkeypatch.setattr(tts.turso, "execute", _boom)
    tts._set_speaking(True)  # non deve sollevare


def test_bootstrap_runs_create_table_once(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", False)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda sql, args=None: calls.append(sql))

    tts._bootstrap_speaking_flag()
    tts._bootstrap_speaking_flag()

    assert len(calls) == 1
    assert "CREATE TABLE IF NOT EXISTS runtime_flags" in calls[0]


class _FakeStreamingEngine:
    """Registra le frasi ricevute da speak_stream() invece di sintetizzarle
    davvero — verifica solo che _speak_sync() spezzi il testo per frase e
    lo passi a speak_stream() (streaming), non piu' a speak() (un blocco
    unico) — richiesta esplicita di Alessandro (2026-09-15) di ridurre il
    tempo prima di sentire la prima parola."""

    def __init__(self):
        self.streamed_sentences: list[str] = []
        self.speak_called_with: str | None = None

    def speak(self, text):
        self.speak_called_with = text

    async def speak_stream(self, sentences, stop_event):
        async for s in sentences:
            self.streamed_sentences.append(s)


def test_speak_sync_streams_per_sentence_not_as_one_block(monkeypatch):
    engine = _FakeStreamingEngine()
    monkeypatch.setattr(tts, "_shared_engine", engine)

    tts._speak_sync("Prima frase. Seconda frase! Terza?")

    assert engine.speak_called_with is None  # mai il vecchio percorso "un blocco solo"
    assert engine.streamed_sentences == ["Prima frase.", "Seconda frase!", "Terza?"]


def test_speak_sync_swallows_errors_from_streaming_engine(monkeypatch):
    class _BoomEngine:
        async def speak_stream(self, sentences, stop_event):
            raise RuntimeError("motore TTS rotto")

    monkeypatch.setattr(tts, "_shared_engine", _BoomEngine())
    tts._speak_sync("Ciao")  # non deve sollevare


def test_speak_sentence_stream_passes_never_set_stop_event():
    seen = {}

    class _CaptureEngine:
        async def speak_stream(self, sentences, stop_event):
            seen["stop_event"] = stop_event
            async for _ in sentences:
                pass

    asyncio.run(tts._speak_sentence_stream(_CaptureEngine(), "Una frase."))
    assert isinstance(seen["stop_event"], threading.Event)
    assert not seen["stop_event"].is_set()
