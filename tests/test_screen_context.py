import asyncio

from core import screen_context


def test_target_for_teams():
    assert screen_context.target_for("guarda su Teams se ho messaggi") == "teams"
    assert screen_context.target_for("cosa mi hanno scritto su teams") == "teams"


def test_target_for_outlook():
    assert screen_context.target_for("ho mail nuove su Outlook?") == "outlook"
    assert screen_context.target_for("controlla la posta") == "outlook"


def test_target_for_generic_screen():
    assert screen_context.target_for("cosa sto facendo") == "screen"
    assert screen_context.target_for("guarda lo schermo") == "screen"
    assert screen_context.target_for("spiegami cosa sto sviluppando su databricks") == "screen"


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
