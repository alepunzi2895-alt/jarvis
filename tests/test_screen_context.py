import asyncio
from unittest.mock import AsyncMock, patch

from core import screen_context


def test_target_for_teams():
    assert screen_context.target_for("guarda su Teams se ho messaggi") == "teams"
    assert screen_context.target_for("cosa mi hanno scritto su teams") == "teams"


def test_target_for_outlook_no_longer_handled_here():
    # Outlook/mail passano da core/outlook.py (intent dedicato, COM) - qui
    # "controlla la posta" senza altre parole cade a None, non a screen/teams.
    assert screen_context.target_for("controlla la posta") is None


def test_target_for_generic_screen():
    assert screen_context.target_for("cosa sto facendo") == "screen"
    assert screen_context.target_for("guarda lo schermo") == "screen"
    assert screen_context.target_for("spiegami cosa sto sviluppando su databricks") == "screen"


def test_target_for_genie_falls_back_to_screen():
    assert screen_context.target_for("leggimi l'ultima risposta di Genie Code") == "screen"


def test_target_for_teams_takes_priority_over_generic_screen():
    # "teams" e "schermo" nella stessa frase: Teams e' piu' specifico
    assert screen_context.target_for("guarda lo schermo di teams") == "teams"


def test_target_for_none_when_unrelated():
    assert screen_context.target_for("che tempo fa oggi?") is None
    assert screen_context.target_for("apri chrome") is None


def test_capture_unknown_target_returns_none():
    assert asyncio.run(screen_context.capture("qualcosa-di-non-supportato")) is None


def test_capture_desktop_returns_none_on_screenshot_failure(monkeypatch):
    class _FakeExecutor:
        def screenshot(self):
            class _R:
                ok = False
                stdout = ""

            return _R()

    monkeypatch.setattr(screen_context, "_system_executor", _FakeExecutor())
    assert asyncio.run(screen_context.capture("screen")) is None


def test_capture_teams_requests_a_scoped_screenshot():
    # 2026-09-16: "filtra tutto il resto che non serve" — lo screenshot di
    # Teams deve provare a ritagliare sulla regione ARIA "main", non l'intera
    # pagina (vedi BrowserAgent.screenshot(scoped=True)).
    agent = AsyncMock()
    agent.open = AsyncMock()
    agent.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfinto")
    with patch("core.screen_context.browser.get_agent", return_value=agent), patch("asyncio.sleep", AsyncMock()):
        result = asyncio.run(screen_context.capture("teams"))

    agent.screenshot.assert_awaited_once_with(scoped=True)
    assert result is not None
