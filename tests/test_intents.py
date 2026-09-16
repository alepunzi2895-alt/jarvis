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
    assert intents.parse_intent("apri la webcam") is None  # gestito da core.voice.camera, non qui


def test_parse_intent_time_and_weather():
    # Aggiunti il 2026-09-15 per portare la voce sotto i 4-5s: Claude
    # rispondeva gia' bene (data/ora/meteo sono nel SYSTEM prompt) ma con
    # un giro API intero (~3s misurati) per una domanda banale.
    assert intents.parse_intent("che ora è") == {"type": "time"}
    assert intents.parse_intent("che ore sono") == {"type": "time"}
    assert intents.parse_intent("che giorno è oggi") == {"type": "time"}
    assert intents.parse_intent("che tempo fa oggi") == {"type": "weather"}


def test_execute_intent_time_returns_formatted_datetime():
    executor = MagicMock()
    result = intents.execute_intent({"type": "time"}, executor, voice=False)
    assert "Sono le" in result


def test_execute_intent_weather_uses_weather_module(monkeypatch):
    executor = MagicMock()
    monkeypatch.setattr("core.weather.get_weather_line", lambda: "22°C, cielo sereno")
    result = intents.execute_intent({"type": "weather"}, executor, voice=True)
    assert "22°C" in result and "Signore" in result


def test_execute_intent_weather_degrades_gracefully_when_unavailable(monkeypatch):
    executor = MagicMock()
    monkeypatch.setattr("core.weather.get_weather_line", lambda: None)
    result = intents.execute_intent({"type": "weather"}, executor, voice=False)
    assert "non riesco" in result.lower()


def test_long_compound_requests_are_left_to_claude():
    long_text = "apri vs code e crea un nuovo file chiamato test.py con dentro una funzione che stampa ciao"
    assert intents.parse_intent(long_text) is None


def test_parse_intent_project_status():
    assert intents.parse_intent("stato progetti") == {"type": "project_status"}
    assert intents.parse_intent("come vanno i progetti") == {"type": "project_status"}
    assert intents.parse_intent("qual e' la situazione dei progetti") == {"type": "project_status"}


def test_execute_intent_project_status():
    executor = MagicMock()
    with (
        patch("core.project_status.check_all", return_value=["finto"]) as check_all,
        patch("core.project_status.format_report", return_value="report finto") as format_report,
    ):
        result = intents.execute_intent({"type": "project_status"}, executor, voice=False)
    check_all.assert_called_once_with(executor)
    format_report.assert_called_once_with(["finto"], voice=False)
    assert result == "report finto"


def test_parse_intent_briefing():
    assert intents.parse_intent("buongiorno") == {"type": "briefing"}
    assert intents.parse_intent("buongiorno!") == {"type": "briefing"}
    assert intents.parse_intent("dammi il briefing") == {"type": "briefing"}
    assert intents.parse_intent("fammi il punto della giornata") == {"type": "briefing"}


def test_parse_intent_briefing_does_not_steal_a_compound_command():
    # "buongiorno" seguito da un comando vero non deve rubare l'intent —
    # deve restare un comando composto per Claude (o un altro intent).
    assert intents.parse_intent("buongiorno apri chrome") != {"type": "briefing"}


def test_execute_intent_briefing_uses_briefing_module():
    executor = MagicMock()
    with patch("core.briefing.gather_briefing_data", return_value={"x": 1}) as gather, \
         patch("core.briefing.format_briefing", return_value="briefing finto") as fmt:
        result = intents.execute_intent({"type": "briefing"}, executor, voice=False)
    gather.assert_called_once_with(executor)
    fmt.assert_called_once_with({"x": 1}, voice=False)
    assert result == "briefing finto"


def test_parse_intent_trading_pnl():
    assert intents.parse_intent("come va il trading") == {"type": "trading_pnl"}
    assert intents.parse_intent("quanto sto guadagnando col trading") == {"type": "trading_pnl"}
    assert intents.parse_intent("come va l'oro") == {"type": "trading_pnl"}


def test_execute_intent_trading_pnl_disabled(monkeypatch):
    executor = MagicMock()
    monkeypatch.setattr("core.myfxbook.ENABLED", False)
    result = intents.execute_intent({"type": "trading_pnl"}, executor, voice=False)
    assert "non configurato" in result.lower()


def test_execute_intent_trading_pnl_formats_accounts(monkeypatch):
    executor = MagicMock()
    monkeypatch.setattr("core.myfxbook.ENABLED", True)
    with patch("core.myfxbook.get_accounts_sync", return_value=["acc"]) as get_accounts, \
         patch("core.myfxbook.format_accounts", return_value="pnl finto") as fmt:
        result = intents.execute_intent({"type": "trading_pnl"}, executor, voice=True)
    get_accounts.assert_called_once()
    fmt.assert_called_once_with(["acc"], voice=True)
    assert result == "pnl finto"


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


def test_parse_intent_outlook_plain_read():
    assert intents.parse_intent("leggi l'ultima mail") == {"type": "outlook", "unread_count": False}


def test_parse_intent_outlook_unread_count():
    assert intents.parse_intent("quante mail ho non lette?") == {"type": "outlook", "unread_count": True}


def test_execute_intent_outlook_unread_count_calls_count_not_list():
    executor = MagicMock()
    with (
        patch("core.outlook.count_unread_emails_sync", return_value=3) as count_fn,
        patch("core.outlook.list_recent_emails_sync") as list_fn,
        patch("core.outlook.format_unread_count", return_value="Hai 3 mail non lette.") as fmt,
    ):
        result = intents.execute_intent({"type": "outlook", "unread_count": True}, executor, voice=False)
    count_fn.assert_called_once()
    list_fn.assert_not_called()
    fmt.assert_called_once_with(3, voice=False)
    assert result == "Hai 3 mail non lette."


def test_execute_intent_outlook_plain_read_calls_list_not_count():
    executor = MagicMock()
    with (
        patch("core.outlook.list_recent_emails_sync", return_value=["finto"]) as list_fn,
        patch("core.outlook.count_unread_emails_sync") as count_fn,
        patch("core.outlook.format_summary", return_value="Posta in arrivo...") as fmt,
    ):
        result = intents.execute_intent({"type": "outlook", "unread_count": False}, executor, voice=False)
    list_fn.assert_called_once()
    count_fn.assert_not_called()
    fmt.assert_called_once_with(["finto"], voice=False)
    assert result == "Posta in arrivo..."
