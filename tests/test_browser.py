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
    page.url = "https://www.google.com/search?q=x"
    page.inner_text = AsyncMock(return_value="  Hello   \n\n\n\nWorld  ")
    agent, _ = _agent_with_fake_pages([page])
    assert asyncio.run(agent.read()) == "Hello\n\nWorld"


def test_read_no_pages_open():
    agent, _ = _agent_with_fake_pages([])
    assert "nessuna pagina" in asyncio.run(agent.read()).lower()


def test_read_truncates_long_text():
    page = MagicMock()
    page.url = "https://www.google.com/search?q=x"
    page.inner_text = AsyncMock(return_value="x" * 10000)
    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.read())
    assert result.endswith("…")
    assert len(result) <= 6001


def test_read_handles_exception_gracefully():
    page = MagicMock()
    page.url = "https://www.google.com/search?q=x"
    page.inner_text = AsyncMock(side_effect=RuntimeError("boom"))
    agent, _ = _agent_with_fake_pages([page])
    assert "impossibile leggere" in asyncio.run(agent.read()).lower()


# ── lettura mirata Outlook Web (2026-09-16): "deve filtrare tutti i bottoni
# ecc e leggere solo le mail aprendole e facendo un riassunto" ──


def _owa_page(role_document_count=0, role_document_text="", role_options=None):
    page = MagicMock()
    page.url = "https://outlook.office.com/mail/inbox"

    doc_locator = MagicMock()
    doc_locator.count = AsyncMock(return_value=role_document_count)
    doc_first = MagicMock()
    doc_first.inner_text = AsyncMock(return_value=role_document_text)
    doc_locator.first = doc_first

    options = role_options or []
    options_locator = MagicMock()
    options_locator.count = AsyncMock(return_value=len(options))

    def _nth(i):
        row = MagicMock()
        row.inner_text = AsyncMock(return_value=options[i])
        row.click = AsyncMock()
        return row

    options_locator.nth = MagicMock(side_effect=_nth)

    def _get_by_role(role, **kwargs):
        return doc_locator if role == "document" else options_locator

    page.get_by_role = MagicMock(side_effect=_get_by_role)
    page.wait_for_timeout = AsyncMock()
    return page


def test_read_uses_document_role_on_outlook_web():
    page = _owa_page(role_document_count=1, role_document_text="Corpo vero della mail aperta.")
    agent, _ = _agent_with_fake_pages([page])
    assert asyncio.run(agent.read()) == "Corpo vero della mail aperta."
    page.inner_text.assert_not_called()  # mai il body intero quando c'e' un riquadro di lettura


def test_read_falls_back_to_option_role_when_no_mail_open():
    page = _owa_page(role_options=["Mittente A - Oggetto 1", "Mittente B - Oggetto 2"])
    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.read())
    assert "Mittente A" in result and "Mittente B" in result


def test_read_emails_opens_each_row_and_returns_only_reading_pane():
    page = _owa_page(role_options=["riga1", "riga2", "riga3"])
    # Dopo ogni click, get_by_role("document") deve "trovare" la mail aperta —
    # qui semplificato: stesso contenuto per ogni mail, il punto e' che
    # read_emails() clicca ogni riga e chiama _read_scoped(), non il body.
    doc_locator = page.get_by_role("document")
    doc_locator.count = AsyncMock(return_value=1)
    doc_locator.first.inner_text = AsyncMock(side_effect=["Corpo mail 1.", "Corpo mail 2."])

    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.read_emails(count=2))

    assert "Corpo mail 1." in result and "Corpo mail 2." in result
    assert "Mail 1" in result and "Mail 2" in result


def test_read_emails_refuses_off_outlook_host():
    page = MagicMock()
    page.url = "https://www.google.com/"
    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.read_emails())
    assert "outlook" in result.lower()


def test_read_emails_no_messages_in_list():
    page = _owa_page(role_options=[])
    agent, _ = _agent_with_fake_pages([page])
    result = asyncio.run(agent.read_emails())
    assert "nessuna mail" in result.lower()


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


def test_extract_and_execute_dispatches_read_mail():
    agent = MagicMock()
    agent.read_emails = AsyncMock(return_value="Mail 1:\nCorpo.")

    text = 'Ecco.\n\n```browser\n{"action":"read_mail","count":2}\n```'
    with patch("core.browser.get_agent", return_value=agent):
        result = asyncio.run(extract_and_execute(text))

    agent.read_emails.assert_awaited_once_with(2)
    assert "Mail 1" in result
