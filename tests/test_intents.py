from unittest.mock import MagicMock, patch

from core import intents


class _SyncThread:
    """Sostituisce threading.Thread nei test: esegue il target subito (stesso
    thread), cosi' le asserzioni su brain.log_interaction non sono in gara con
    un thread di sfondo che potrebbe non aver ancora girato (execute_intent lo
    lancia fire-and-forget, senza join, apposta per non bloccare la risposta)."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def test_open_and_close_app():
    assert intents.parse_intent("apri chrome") == {"type": "open_app", "name": "chrome"}
    assert intents.parse_intent("chiudi chrome") == {"type": "close_app", "name": "chrome"}
    assert intents.parse_intent("spegni chrome") == {"type": "close_app", "name": "chrome"}


def test_power_actions_take_priority_over_app_matching():
    assert intents.parse_intent("spegni il pc") == {"type": "power", "mode": "shutdown"}
    assert intents.parse_intent("riavvia il computer") == {"type": "power", "mode": "restart"}


def test_volume_and_lock_and_screenshot():
    assert intents.parse_intent("alza il volume") == {"type": "volume", "direction": "up"}
    assert intents.parse_intent("abbassa il volume") == {"type": "volume", "direction": "down"}
    assert intents.parse_intent("blocca lo schermo") == {"type": "lock"}
    assert intents.parse_intent("fai uno screenshot") == {"type": "screenshot"}


def test_generic_questions_are_not_intercepted():
    assert intents.parse_intent("quanto fa 12 per 8") is None
    assert intents.parse_intent("che tempo fa oggi") is None
    assert intents.parse_intent("apri la webcam") is None  # gestito da core.voice.camera, non qui


def test_long_compound_requests_are_left_to_claude():
    long_text = "apri vs code e crea un nuovo file chiamato test.py con dentro una funzione che stampa ciao"
    assert intents.parse_intent(long_text) is None


def test_execute_intent_power_refuses_on_voice():
    executor = MagicMock()
    result = intents.execute_intent({"type": "power", "mode": "shutdown"}, executor, voice=True)
    assert "non gestisco" in result.lower()
    executor.power_action.assert_not_called()


def test_execute_intent_power_stages_confirmation_on_text():
    executor = MagicMock()
    executor.power_action.return_value = MagicMock(needs_confirmation=True, token="abc123")
    result = intents.execute_intent({"type": "power", "mode": "shutdown"}, executor, voice=False)
    assert "abc123" in result


def test_execute_intent_open_app():
    executor = MagicMock()
    executor.open_app.return_value = MagicMock(ok=True)
    result = intents.execute_intent({"type": "open_app", "name": "chrome"}, executor, voice=False)
    assert "chrome" in result.lower()
    executor.open_app.assert_called_once_with("chrome")


def test_execute_intent_logs_interaction_when_turso_enabled(monkeypatch):
    monkeypatch.setattr("core.turso.ENABLED", True)
    monkeypatch.setattr("core.intents.threading.Thread", _SyncThread)
    executor = MagicMock()
    executor.open_app.return_value = MagicMock(ok=True)
    with patch("core.brain.log_interaction") as log:
        intents.execute_intent(
            {"type": "open_app", "name": "chrome"}, executor, voice=False, workspace="jarvis", raw_text="apri chrome"
        )
    log.assert_called_once_with("apri chrome", "jarvis", "text")


def test_execute_intent_logs_voice_channel_and_falls_back_to_a_label(monkeypatch):
    monkeypatch.setattr("core.turso.ENABLED", True)
    monkeypatch.setattr("core.intents.threading.Thread", _SyncThread)
    executor = MagicMock()
    executor.lock_workstation.return_value = MagicMock(ok=True)
    with patch("core.brain.log_interaction") as log:
        intents.execute_intent({"type": "lock"}, executor, voice=True)  # niente raw_text
    assert log.call_args.args[1] == "jarvis"  # workspace di default
    assert log.call_args.args[2] == "voice"
    assert "lock" in log.call_args.args[0]


def test_execute_intent_skips_logging_when_turso_disabled():
    # turso.ENABLED e' gia' False di default nei test (tests/conftest.py)
    executor = MagicMock()
    executor.open_app.return_value = MagicMock(ok=True)
    with patch("core.brain.log_interaction") as log:
        intents.execute_intent({"type": "open_app", "name": "chrome"}, executor, voice=False)
    log.assert_not_called()
