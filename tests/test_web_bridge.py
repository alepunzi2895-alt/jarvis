import asyncio

import pytest

from core import web_bridge
from core.web_bridge import _strip_wake_word


def test_wake_word_present_strips_prefix():
    assert _strip_wake_word("Jarvis apri chrome") == "apri chrome"


def test_wake_word_case_insensitive_and_mid_sentence():
    assert _strip_wake_word("ehi JARVIS, che ore sono") == "che ore sono"


def test_no_wake_word_is_ignored():
    assert _strip_wake_word("stavo giusto guardando la tv") is None


def test_wake_word_alone_is_ignored():
    assert _strip_wake_word("Jarvis") is None


def test_wake_word_followed_by_noise_word_is_ignored():
    assert _strip_wake_word("jarvis eh") is None


def test_substring_of_wake_word_does_not_match():
    assert _strip_wake_word("jarvisone apri chrome") is None


def test_wake_word_phonetic_variant_yarvis_matches():
    # Osservato dal vivo (2026-09-15): whisper in italiano puo' trascrivere
    # "Jarvis" foneticamente come "YARVIS" - senza questa variante il
    # comando sarebbe stato scartato in silenzio nonostante fosse valido.
    assert _strip_wake_word("YARVIS leggi l'ultima mail") == "leggi l'ultima mail"


def test_wake_word_phonetic_variant_giarvis_matches():
    assert _strip_wake_word("giarvis apri chrome") == "apri chrome"


def test_wake_word_unrelated_word_ending_in_arvis_does_not_match():
    assert _strip_wake_word("questo scarvis non esiste apri chrome") is None


def test_known_hallucination_phrase_is_ignored():
    assert _strip_wake_word("Il maggiordomo AI di Iron Man.") is None
    assert _strip_wake_word("Sottotitoli e revisione a cura di QTSS.") is None
    assert _strip_wake_word("Buon appetito!") is None


def test_wake_word_far_from_start_is_ignored():
    long_ramble = (
        "e male che va scendiamo ci ho contatto un po' la scendiamo cosi "
        "la pilliamo e poi arrivo jarvis apri chrome"
    )
    assert _strip_wake_word(long_ramble) is None


def test_wake_word_still_matches_with_short_lead_in():
    assert _strip_wake_word("ok, adesso jarvis apri chrome") == "apri chrome"


class _StopLoop(Exception):
    """Interrompe poll_web_queue() dopo un ciclo, per testarlo senza
    farlo girare per sempre (e' un while True)."""


def test_empty_transcription_is_ignored_not_shown_as_error(monkeypatch):
    """Da quando stt.py filtra il rumore con vad_filter (2026-09-15), una
    trascrizione vuota e' quasi sempre silenzio/rumore correttamente
    scartato, non un vero tentativo di comando fallito. Prima di questo
    fix veniva pushato come status="error" con un messaggio parlato/
    visibile ("Non ho capito niente..., Riprova.") ad ogni falso trigger
    del mic a mani libere — regressione osservata dal vivo il 2026-09-15
    subito dopo l'introduzione di vad_filter."""
    updates: list[tuple[str, list]] = []
    calls = {"select": 0}

    def fake_execute(query, params=None):
        if query.startswith("SELECT"):
            calls["select"] += 1
            if calls["select"] > 1:
                raise _StopLoop()
            return [{
                "id": "t1", "channel": "web", "workspace": "jarvis",
                "prompt": "", "image_b64": None, "audio_b64": "AAAA",
            }]
        updates.append((query, params))
        return []

    async def fake_transcribe(_audio_b64: str) -> str:
        return ""

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)
    monkeypatch.setattr(web_bridge, "_transcribe_audio", fake_transcribe)
    monkeypatch.setattr(web_bridge.asyncio, "sleep", lambda _s: asyncio.sleep(0))

    with pytest.raises(_StopLoop):
        asyncio.run(web_bridge.poll_web_queue())

    result_updates = [p for q, p in updates if "status=?" in q]
    assert len(result_updates) == 1
    status, result, _session_id, _cost, _task_id = result_updates[0]
    assert status == "ignored"
    assert result == ""


def test_voice_command_triggers_barge_in_stop(monkeypatch):
    """Un comando vocale valido (wake word + testo) deve interrompere subito
    la voce eventualmente ancora in corso — barge-in richiesto esplicitamente
    da Alessandro (2026-09-15): "quando dico hey jarvis mentre sta parlando
    vorrei si interrompesse". stop_current_speech() e' innocuo se JARVIS non
    stava parlando, quindi va chiamato incondizionatamente per ogni comando
    vocale riconosciuto, non solo quando si sa gia' che stava parlando."""
    calls = {"select": 0}
    updates: list[tuple[str, list]] = []
    stop_calls = []

    def fake_execute(query, params=None):
        if query.startswith("SELECT"):
            calls["select"] += 1
            if calls["select"] > 1:
                raise _StopLoop()
            return [{
                "id": "t1", "channel": "web", "workspace": "jarvis",
                "prompt": "", "image_b64": None, "audio_b64": "AAAA",
            }]
        updates.append((query, params))
        return []

    async def fake_transcribe(_audio_b64: str) -> str:
        return "jarvis che ore sono"

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)
    monkeypatch.setattr(web_bridge, "_transcribe_audio", fake_transcribe)
    monkeypatch.setattr(web_bridge.asyncio, "sleep", lambda _s: asyncio.sleep(0))
    monkeypatch.setattr(web_bridge.tts, "stop_current_speech", lambda: stop_calls.append(True))
    monkeypatch.setattr(web_bridge.intents, "parse_intent", lambda _text: {"type": "time"})
    monkeypatch.setattr(web_bridge.intents, "execute_intent", lambda *a, **k: "Sono le 18:00, Signore.")
    monkeypatch.setattr(web_bridge.tts, "speak_if_enabled", lambda _text: None)
    monkeypatch.setattr(web_bridge, "_notify_telegram", lambda *a, **k: None)

    with pytest.raises(_StopLoop):
        asyncio.run(web_bridge.poll_web_queue())

    assert stop_calls == [True]


def test_intent_result_is_tagged_with_auto_detected_workspace(monkeypatch):
    """Il progetto non arriva piu' dal client (pill rimosse dalla dashboard,
    2026-09-16: "non mi piace avere tutti quei contesti sopra") - va
    rilevato dal testo del task e scritto indietro nella riga, cosi' la
    dashboard puo' comunque mostrarlo (HUD/cronologia) senza che l'utente
    lo scelga a mano."""
    calls = {"select": 0}
    updates: list[tuple[str, list]] = []
    captured = {}

    def fake_execute(query, params=None):
        if query.startswith("SELECT"):
            calls["select"] += 1
            if calls["select"] > 1:
                raise _StopLoop()
            return [{
                "id": "t1", "channel": "web", "workspace": "jarvis",
                "prompt": "aura, che ore sono?", "image_b64": None, "audio_b64": None,
            }]
        updates.append((query, params))
        return []

    def fake_execute_intent(intent, executor, voice_flag, ws, prompt):
        captured["ws"] = ws
        return "Sono le 18:00, Signore."

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)
    monkeypatch.setattr(web_bridge.asyncio, "sleep", lambda _s: asyncio.sleep(0))
    monkeypatch.setattr(web_bridge.intents, "parse_intent", lambda _text: {"type": "time"})
    monkeypatch.setattr(web_bridge.intents, "execute_intent", fake_execute_intent)
    monkeypatch.setattr(web_bridge.tts, "speak_if_enabled", lambda _text: None)
    monkeypatch.setattr(web_bridge, "_notify_telegram", lambda *a, **k: None)

    with pytest.raises(_StopLoop):
        asyncio.run(web_bridge.poll_web_queue())

    assert captured["ws"] == "aura"
    result_updates = [p for q, p in updates if "workspace=?" in q]
    assert len(result_updates) == 1
    _status, _result, _session_id, _cost, workspace, _task_id = result_updates[0]
    assert workspace == "aura"
