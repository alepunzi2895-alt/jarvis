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


def test_speak_sentence_stream_forwards_given_stop_event():
    """Dal 2026-09-15 lo stop_event non e' piu' creato al volo qui dentro
    (era sempre "mai settato" perche' nessuno ci teneva un riferimento) —
    ora arriva da fuori (_speak_sync) cosi' web_bridge.py puo' interromperlo
    davvero (barge-in dal mic della dashboard mentre JARVIS parla)."""
    seen = {}

    class _CaptureEngine:
        async def speak_stream(self, sentences, stop_event):
            seen["stop_event"] = stop_event
            async for _ in sentences:
                pass

    given_event = threading.Event()
    asyncio.run(tts._speak_sentence_stream(_CaptureEngine(), "Una frase.", given_event))
    assert seen["stop_event"] is given_event


def test_stop_current_speech_noop_when_nothing_speaking(monkeypatch):
    monkeypatch.setattr(tts, "_current_stop_event", None)
    monkeypatch.setattr(tts, "_shared_engine", None)
    tts.stop_current_speech()  # non deve sollevare


def test_stop_current_speech_sets_event_and_stops_engine(monkeypatch):
    event = threading.Event()
    monkeypatch.setattr(tts, "_current_stop_event", event)

    class _FakeEngine:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    engine = _FakeEngine()
    monkeypatch.setattr(tts, "_shared_engine", engine)

    tts.stop_current_speech()

    assert event.is_set()
    assert engine.stopped is True


def test_speak_sync_exposes_and_clears_current_stop_event(monkeypatch):
    """Verifica il ciclo di vita reale usato da web_bridge.py: durante
    _speak_sync() _current_stop_event punta all'evento di quella chiamata
    (cosi' stop_current_speech() puo' fermarla), e torna a None quando
    finisce (cosi' un stop_current_speech() dopo non fa nulla di strano)."""
    seen_event_during_call = {}

    class _CaptureEngine:
        async def speak_stream(self, sentences, stop_event):
            seen_event_during_call["event"] = stop_event
            assert tts._current_stop_event is stop_event
            async for _ in sentences:
                pass

    monkeypatch.setattr(tts, "_shared_engine", _CaptureEngine())
    monkeypatch.setattr(tts, "_current_stop_event", None)

    tts._speak_sync("Ciao Signore.")

    assert seen_event_during_call["event"] is not None
    assert tts._current_stop_event is None
