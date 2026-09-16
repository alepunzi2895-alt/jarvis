import asyncio
from unittest.mock import AsyncMock, patch

from core.mail_actions import extract_and_execute
from core.outlook import OutlookError


def test_extract_and_execute_creates_draft():
    text = (
        "Ecco la risposta.\n\n"
        '```mail_draft\n{"to":"mario@example.com","subject":"Ciao","body":"Testo bozza"}\n```'
    )
    with patch("core.mail_actions.outlook.create_draft_email", new=AsyncMock(return_value="Bozza creata.")) as fake:
        result = asyncio.run(extract_and_execute(text))

    fake.assert_awaited_once_with("mario@example.com", "Ciao", "Testo bozza")
    assert "Bozza creata." in result
    assert "```mail_draft" not in result


def test_extract_and_execute_no_block_returns_text_unchanged():
    text = "Nessun blocco qui."
    assert asyncio.run(extract_and_execute(text)) == text


def test_extract_and_execute_skips_block_missing_to_or_body():
    text = '```mail_draft\n{"subject":"Ciao"}\n```'
    with patch("core.mail_actions.outlook.create_draft_email", new=AsyncMock()) as fake:
        result = asyncio.run(extract_and_execute(text))
    fake.assert_not_awaited()
    assert "```mail_draft" not in result


def test_extract_and_execute_reports_outlook_error():
    text = '```mail_draft\n{"to":"a@b.com","body":"x"}\n```'
    with patch("core.mail_actions.outlook.create_draft_email", new=AsyncMock(side_effect=OutlookError("Outlook non disponibile"))):
        result = asyncio.run(extract_and_execute(text))
    assert "Outlook non disponibile" in result


def test_extract_and_execute_ignores_malformed_json():
    text = "```mail_draft\nnon e' json\n```"
    result = asyncio.run(extract_and_execute(text))
    assert "```mail_draft" not in result
