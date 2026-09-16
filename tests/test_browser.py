import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.browser import BrowserAgent, extract_and_execute


def test_open_refuses_localhost_without_touching_playwright():
    agent = BrowserAgent()
    result = asyncio.run(agent.open("http://localhost:3000/"))
    assert "non apro" in result.lower()
    assert agent._context is None  # mai avviato Playwright per un indirizzo locale


def test_open_refuses_127_0_0_1():
    agent = BrowserAgent()
    result = asyncio.run(agent.open("http://127.0.0.1:8080/"))
    assert "non apro" in result.lower()


def test_open_refuses_localhost_regardless_of_port_or_path():
    agent = BrowserAgent()
    result = asyncio.run(agent.open("http://localhost/second-brain"))
    assert "non apro" in result.lower()


# ── read/click/type ("voglio poter leggere e capire cosa c'e' sulla pagina...
# e anche interagire, es aprire genie code e scrivere un input", 2026-09-15) ──
# Verificato anche dal vivo (non solo qui) contro una pagina di test reale con
# Playwright vero: bottone che apre un pannello con un contenteditable,
# read->click->read->type->read ha funzionato esattamente come i test sotto
# si aspettano (compreso il fallback su contenteditable quando nulla e' a
# fuoco). Qui i mock isolano solo la logica di dispatch/pulizia testo.

def _agent_with_fake_pages(pages):
    agent = BrowserAgent()
    context = MagicMock()
    context.pages = pages
    agent._context = context  # bypassa _ensure_context: niente Playwright vero
    return agent, context


def test_read_returns_cleaned_body_text():
    page = MagicMock()
    page.inner_text = AsyncMock(return_value="  Hello   \n\n\n\nWorld  ")
    agent, _ = _agent_with_fake_pages([page])
    assert asyncio.run(agent.read()) == "Hello\n\nWorld"


def test_read_no_pages_open():
    agent, _ = _agent_with_fake_pages([])
    assert "nessuna pagina" in asyncio.run(agent.read()).lower()


def test_read_truncates_long_text():
    page = MagicMock()
    page.inner_text = AsyncMock(return_value="x" * 10000)
    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.read())
    assert result.endswith("…")
    assert len(result) <= 6001


def test_read_handles_exception_gracefully():
    page = MagicMock()
    page.inner_text = AsyncMock(side_effect=RuntimeError("boom"))
    agent, _ = _agent_with_fake_pages([page])
    assert "impossibile leggere" in asyncio.run(agent.read()).lower()


def test_click_finds_and_clicks_by_visible_text():
    page = MagicMock()
    locator = MagicMock()
    locator.first.click = AsyncMock()
    page.get_by_text = MagicMock(return_value=locator)
    agent, _ = _agent_with_fake_pages([page])
    with patch("core.browser.bring_matching_to_foreground_bg"):
        result = asyncio.run(agent.click("Genie Code"))
    page.get_by_text.assert_called_once_with("Genie Code", exact=False)
    locator.first.click.assert_awaited_once()
    assert "cliccato" in result.lower()


def test_click_reports_failure_when_element_not_found():
    page = MagicMock()
    locator = MagicMock()
    locator.first.click = AsyncMock(side_effect=RuntimeError("not found"))
    page.get_by_text = MagicMock(return_value=locator)
    agent, _ = _agent_with_fake_pages([page])
    assert "non ho trovato" in asyncio.run(agent.click("Nope")).lower()


def test_click_no_pages_open():
    agent, _ = _agent_with_fake_pages([])
    assert "nessuna pagina" in asyncio.run(agent.click("x")).lower()


def test_type_text_uses_already_focused_element():
    page = MagicMock()
    page.url = "https://example.com/page"
    page.evaluate = AsyncMock(return_value="TEXTAREA:")
    page.locator = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.type_text("ciao"))
    page.locator.assert_not_called()  # gia' a fuoco: nessun bisogno di cercare un campo
    page.keyboard.type.assert_awaited_once_with("ciao", delay=15)
    page.keyboard.press.assert_awaited_once_with("Enter")
    assert "scritto" in result.lower() and "inviato" in result.lower()


def test_type_text_falls_back_to_last_input_when_nothing_focused():
    page = MagicMock()
    page.url = "https://example.com/page"
    page.evaluate = AsyncMock(return_value="BODY:")
    locator = MagicMock()
    locator.last.click = AsyncMock()
    page.locator = MagicMock(return_value=locator)
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.type_text("ciao", submit=False))
    locator.last.click.assert_awaited_once()
    page.keyboard.press.assert_not_called()
    assert "inviato" not in result.lower()


def test_type_text_no_pages_open():
    agent, _ = _agent_with_fake_pages([])
    assert "nessuna pagina" in asyncio.run(agent.type_text("x")).lower()


# ── draft-mode forzato su Teams/Outlook (mai invio automatico, a livello di
# codice non solo di prompt — richiesta esplicita di Alessandro, 2026-09-16) ──

def test_type_text_forces_draft_on_teams_even_if_submit_true():
    page = MagicMock()
    page.url = "https://teams.microsoft.com/v2/"
    page.evaluate = AsyncMock(return_value="TEXTAREA:")
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    agent, _ = _agent_with_fake_pages([page])

    result = asyncio.run(agent.type_text("ciao", submit=True))

    page.keyboard.press.assert_not_called()  # mai Invio, a prescindere da submit=True
    assert "bozza" in result.lower()


def test_type_text_forces_draft_on_outlook_web():
    page = MagicMock()
    page.url = "https://outlook.office.com/mail/inbox"
    page.evaluate = AsyncMock(return_value="TEXTAREA:")
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    agent, _ = _agent_with_fake_pages([page])

    asyncio.run(agent.type_text("ciao", submit=True))

    page.keyboard.press.assert_not_called()


def test_type_text_does_not_force_draft_on_other_sites():
    page = MagicMock()
    page.url = "https://www.google.com/search?q=x"
    page.evaluate = AsyncMock(return_value="TEXTAREA:")
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    agent, _ = _agent_with_fake_pages([page])

    result = asyncio.run(agent.type_text("ciao", submit=True))

    page.keyboard.press.assert_awaited_once_with("Enter")
    assert "bozza" not in result.lower()


def test_extract_and_execute_dispatches_read_click_type():
    agent = MagicMock()
    agent.read = AsyncMock(return_value="testo pagina")
    agent.click = AsyncMock(return_value="cliccato")
    agent.type_text = AsyncMock(return_value="scritto")

    text = (
        "Ecco.\n\n```browser\n{\"action\":\"read\"}\n```\n"
        "```browser\n{\"action\":\"click\",\"text\":\"Genie Code\"}\n```\n"
        "```browser\n{\"action\":\"type\",\"text\":\"ciao\",\"submit\":false}\n```"
    )
    with patch("core.browser.get_agent", return_value=agent):
        result = asyncio.run(extract_and_execute(text))

    agent.click.assert_awaited_once_with("Genie Code")
    agent.type_text.assert_awaited_once_with("ciao", False)
    assert "testo pagina" in result and "cliccato" in result and "scritto" in result
