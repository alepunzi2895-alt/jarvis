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


def test_wake_word_survives_longer_noise_prefix_from_stt():
    # Caso reale osservato in logs/bot.log il 2026-09-16: un comando VERO
    # scartato perche' whisper aveva trascritto rumore/un'allucinazione
    # PRIMA della parola d'attivazione, spostandola oltre la vecchia
    # soglia di 24 caratteri (segnalato: "non intercetta il comando
    # vocale"). La soglia (40) deve tollerare questo prefisso pur
    # continuando a respingere una wake word sepolta in una frase lunga
    # (vedi test_wake_word_far_from_start_is_ignored, ~90 caratteri).
    result = _strip_wake_word("È una sbarpa di caggina.  Jarvis, che tempo farà domani?")
    assert result == "che tempo farà domani?"


# ── _claim_next_task / _supersede_older: "ad ogni domanda nuova killa
# tutti i vecchi processi" (Alessandro, 2026-09-16) — ma solo un comando
# vero supera gli altri, mai il rumore captato dal mic a mani libere
# (2026-10-12: pulsanti e testo scritto venivano superati da rumore).


def test_claim_next_task_prefers_certain_commands_and_never_supersedes(monkeypatch):
    executed: list[tuple[str, list | None]] = []

    def fake_execute(query, params=None):
        executed.append((query, params))
        if query.startswith("SELECT"):
            return [{
                "id": "button", "channel": "web", "workspace": "jarvis",
                "prompt": "come vanno i progetti?", "image_b64": None, "audio_b64": None,
                "created_at": "2026-10-12 20:07:04", "age_sec": "2",
            }]
        return []

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)

    task = asyncio.run(web_bridge._claim_next_task())

    assert task["id"] == "button"
    select = executed[0][0]
    # Prima i task senza audio (i piu' recenti), poi l'audio in ordine di arrivo.
    assert "ORDER BY (audio_b64 IS NOT NULL)" in select
    assert "created_at ASC" in select
    assert not [q for q, _p in executed if "superseded" in q]
    assert len([q for q, _p in executed if "'running'" in q]) == 1


def test_claim_next_task_expires_stale_audio_then_claims_next(monkeypatch):
    executed: list[tuple[str, list | None]] = []
    rows = [
        [{"id": "old", "audio_b64": "AAAA", "created_at": "2026-10-12 20:00:00", "age_sec": "300"}],
        [{"id": "fresh", "audio_b64": "AAAA", "created_at": "2026-10-12 20:04:58", "age_sec": "2"}],
    ]

    def fake_execute(query, params=None):
        executed.append((query, params))
        if query.startswith("SELECT"):
            return rows.pop(0)
        return []

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)

    task = asyncio.run(web_bridge._claim_next_task())

    assert task["id"] == "fresh"
    expire = [(q, p) for q, p in executed if "superseded" in q]
    assert len(expire) == 1
    assert "audio_b64 IS NOT NULL" in expire[0][0]
    assert expire[0][1] == [f"-{web_bridge.AUDIO_TASK_MAX_AGE_SEC} seconds"]


def test_supersede_older_only_touches_older_pending_rows(monkeypatch):
    executed: list[tuple[str, list | None]] = []
    monkeypatch.setattr(web_bridge.turso, "execute", lambda q, p=None: executed.append((q, p)))

    asyncio.run(web_bridge._supersede_older({"id": "t9", "created_at": "2026-10-12 20:07:30"}))

    query, params = executed[0]
    assert "status='pending'" in query and "created_at <= ?" in query
    assert params == ["t9", "2026-10-12 20:07:30"]


def _run_one_audio_task(monkeypatch, transcript: str) -> list[tuple[str, list | None]]:
    calls = {"select": 0}
    updates: list[tuple[str, list | None]] = []

    def fake_execute(query, params=None):
        if query.startswith("SELECT"):
            calls["select"] += 1
            if calls["select"] > 1:
                raise _StopLoop()
            return [{
                "id": "a1", "channel": "transcribe", "workspace": "jarvis", "prompt": "",
                "image_b64": None, "audio_b64": "AAAA", "created_at": "2026-10-12 20:08:57",
            }]
        updates.append((query, params))
        return []

    async def fake_transcribe(_audio_b64: str) -> str:
        return transcript

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)
    monkeypatch.setattr(web_bridge, "_transcribe_audio", fake_transcribe)
    monkeypatch.setattr(web_bridge.asyncio, "sleep", lambda _s: asyncio.sleep(0))
    monkeypatch.setattr(web_bridge.tts, "stop_current_speech", lambda: None)
    monkeypatch.setattr(web_bridge.tts, "speak_if_enabled", lambda _text: None)
    monkeypatch.setattr(web_bridge, "_notify_telegram", lambda *a, **k: None)
    monkeypatch.setattr(web_bridge.intents, "parse_intent", lambda _text: {"type": "time"})
    monkeypatch.setattr(web_bridge.intents, "execute_intent", lambda *a, **k: "Sono le 22:08.")
    monkeypatch.setattr(web_bridge, "_wake_armed_at", None)

    with pytest.raises(_StopLoop):
        asyncio.run(web_bridge.poll_web_queue())
    return updates


def test_background_speech_does_not_supersede_pending_commands(monkeypatch):
    updates = _run_one_audio_task(monkeypatch, "Ma va via, non ho sentito.")

    assert not [q for q, _p in updates if "superseded" in q]
    assert [p[0] for q, p in updates if "status=?" in q] == ["ignored"]


def test_real_voice_command_supersedes_older_pending(monkeypatch):
    updates = _run_one_audio_task(monkeypatch, "Jarvis, che ore sono?")

    assert [p for q, p in updates if "superseded" in q] == [["a1", "2026-10-12 20:08:57"]]
    assert [p[0] for q, p in updates if "status=?" in q] == ["done"]


# ── "Jarvis" + pausa + comando: arriva in due segmenti separati.


def test_wake_word_then_pause_then_command(monkeypatch):
    monkeypatch.setattr(web_bridge, "_wake_armed_at", None)

    assert web_bridge._resolve_voice_command("Jarvis.", "2026-10-12 20:08:43") is None
    assert web_bridge._resolve_voice_command("Apri la fotocamera.", "2026-10-12 20:08:48") == "Apri la fotocamera"
    # Consumata: la frase dopo non e' piu' un comando.
    assert web_bridge._resolve_voice_command("E poi chiudi tutto.", "2026-10-12 20:08:50") is None


def test_wake_word_followup_expires(monkeypatch):
    monkeypatch.setattr(web_bridge, "_wake_armed_at", None)

    assert web_bridge._resolve_voice_command("Jarvis.", "2026-10-12 20:08:43") is None
    late = "2026-10-12 20:09:30"
    assert web_bridge._resolve_voice_command("apri la fotocamera", late) is None


def test_wake_word_followup_still_drops_hallucinations(monkeypatch):
    monkeypatch.setattr(web_bridge, "_wake_armed_at", None)

    web_bridge._resolve_voice_command("ehi Jarvis", "2026-10-12 20:08:43")
    assert web_bridge._resolve_voice_command("Sottotitoli e revisione a cura di QTSS.", "2026-10-12 20:08:45") is None
    assert web_bridge._resolve_voice_command("che tempo fa domani", "2026-10-12 20:08:47") == "che tempo fa domani"


def test_ordinary_background_speech_is_never_a_command(monkeypatch):
    monkeypatch.setattr(web_bridge, "_wake_armed_at", None)

    assert web_bridge._resolve_voice_command("La pubblicata poco. Sì?", "2026-10-12 20:08:57") is None


def test_claim_next_task_no_pending_returns_none(monkeypatch):
    def fake_execute(query, params=None):
        return [] if query.startswith("SELECT") else None

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)
    assert asyncio.run(web_bridge._claim_next_task()) is None


def test_recover_interrupted_tasks_marks_running_rows_as_error(monkeypatch):
    calls: list[tuple[str, list | None]] = []

    def fake_execute(query, params=None):
        calls.append((query, params))
        return [{"rows_affected": 3}]

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)

    assert asyncio.run(web_bridge.recover_interrupted_tasks()) == 3
    query, params = calls[0]
    assert "status='error'" in query
    assert "WHERE status='running'" in query
    assert params == ["Interrotto: il bridge locale si e' riavviato. Invia di nuovo la richiesta."]


def test_recover_interrupted_tasks_does_not_block_on_turso_error(monkeypatch):
    def fake_execute(_query, _params=None):
        raise OSError("rete assente")

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)

    assert asyncio.run(web_bridge.recover_interrupted_tasks()) == 0


def test_run_claude_timeout_keeps_queue_responsive(monkeypatch):
    """2026-09-16: un comando reale ("apri chrome e metti Battiato su
    YouTube") ha bloccato l'intero poller — nessuna nuova riga in bot.log,
    CPU ferma, per minuti. Con RUN_CLAUDE_TIMEOUT_SEC un run_claude() che
    non ritorna mai non deve piu' bloccare il loop per sempre: il task va
    comunque in "done" con un messaggio onesto, cosi' il prossimo task in
    coda viene comunque processato."""
    calls = {"select": 0}
    updates: list[tuple[str, list]] = []

    def fake_execute(query, params=None):
        if query.startswith("SELECT"):
            calls["select"] += 1
            if calls["select"] > 1:
                raise _StopLoop()
            return [{
                "id": "t1", "channel": "web", "workspace": "jarvis",
                "prompt": "apri chrome e metti Battiato su YouTube", "image_b64": None, "audio_b64": None,
            }]
        updates.append((query, params))
        return []

    async def hanging_run_claude(*_a, **_k):
        # asyncio.Event().wait() invece di asyncio.sleep(): il test rimpiazza
        # asyncio.sleep per non aspettare davvero POLL_SEC tra un giro e
        # l'altro, il che farebbe finire anche questa "attesa infinita"
        # subito se usasse la stessa funzione.
        await asyncio.Event().wait()

    monkeypatch.setattr(web_bridge, "RUN_CLAUDE_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)
    monkeypatch.setattr(web_bridge, "run_claude", hanging_run_claude)
    monkeypatch.setattr(web_bridge.intents, "parse_intent", lambda _text: None)
    monkeypatch.setattr(web_bridge.asyncio, "sleep", lambda _s: asyncio.sleep(0))
    monkeypatch.setattr(web_bridge.tts, "speak_if_enabled", lambda _text: None)
    monkeypatch.setattr(web_bridge, "_notify_telegram", lambda *a, **k: None)
    monkeypatch.setattr(web_bridge.screen_context, "target_for", lambda _t: None)
    monkeypatch.setattr(web_bridge.camera, "wants_camera", lambda _t: False)

    with pytest.raises(_StopLoop):
        asyncio.run(web_bridge.poll_web_queue())

    result_updates = [p for q, p in updates if "status=?" in q]
    assert len(result_updates) == 1
    status, result = result_updates[0][0], result_updates[0][1]
    assert status == "done"
    assert "troppo tempo" in result.lower()


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


def test_every_finished_task_prunes_audio_to_the_latest_few(monkeypatch):
    """Gli audio restavano in Turso per sempre (1,26 GB al 2026-10-12):
    ora restano solo gli ultimi AUDIO_KEEP, mai quelli ancora in coda."""
    executed: list[tuple[str, list | None]] = []
    monkeypatch.setattr(web_bridge.turso, "execute", lambda q, p=None: executed.append((q, p)))

    asyncio.run(web_bridge._push_result("t1", "ignored", "", None, 0.0))
    asyncio.run(web_bridge._push_result("t2", "done", "ok", None, 0.0, workspace="jarvis"))

    prunes = [(q, p) for q, p in executed if "audio_b64=NULL" in q]
    assert len(prunes) == 2
    query, params = prunes[0]
    assert "status NOT IN ('pending', 'running')" in query
    assert "ORDER BY created_at DESC LIMIT ?" in query
    assert params == [web_bridge.AUDIO_KEEP] == [5]


def test_prune_failure_does_not_block_result_delivery(monkeypatch):
    statuses = []

    def fake_execute(query, params=None):
        if "audio_b64=NULL" in query:
            raise OSError("rete assente")
        statuses.append(params[0])

    monkeypatch.setattr(web_bridge.turso, "execute", fake_execute)

    asyncio.run(web_bridge._push_result("t1", "done", "ok", None, 0.0))

    assert statuses == ["done"]


def test_ensure_indexes_creates_queue_and_audio_indexes(monkeypatch):
    executed: list[str] = []
    monkeypatch.setattr(web_bridge.turso, "execute", lambda q, p=None: executed.append(q))

    asyncio.run(web_bridge.ensure_indexes())

    assert any("ON tasks(status, created_at)" in q for q in executed)
    assert any("WHERE audio_b64 IS NOT NULL" in q for q in executed)
