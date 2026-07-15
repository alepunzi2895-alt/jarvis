from unittest.mock import MagicMock

from core import intents


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
