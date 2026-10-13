import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

import pytest

import bot


def test_transcribe_telegram_voice_downloads_and_transcribes(monkeypatch):
    """Nota vocale Telegram (2026-09-15): scarica il file via getFile +
    download diretto, poi lo trascrive con lo stesso motore whisper del
    resto del repo — nessun filtro parola d'attivazione (a differenza del
    mic sempre acceso della dashboard), mandare una nota vocale e' gia'
    un'azione esplicita."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        resp = MagicMock()
        if "getFile" in url:
            resp.json.return_value = {"result": {"file_path": "voice/file123.oga"}}
        else:
            resp.content = b"finti-byte-audio"
        return resp

    monkeypatch.setattr(bot.requests, "get", fake_get)
    monkeypatch.setattr(bot, "TOKEN", "TESTTOKEN")
    monkeypatch.setattr(bot, "API", "https://api.telegram.org/botTESTTOKEN")

    with patch("core.voice.stt.transcribe_file", return_value="leggi l'ultima mail") as transcribe:
        text = asyncio.run(bot._transcribe_telegram_voice("file_id_abc"))

    assert text == "leggi l'ultima mail"
    transcribe.assert_called_once()
    assert any("getFile" in c for c in calls)
    assert any("file_id_abc" not in c and "voice/file123.oga" in c for c in calls)


def test_transcribe_telegram_voice_returns_empty_string_on_silence(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        resp = MagicMock()
        resp.json.return_value = {"result": {"file_path": "voice/file123.oga"}}
        resp.content = b""
        return resp

    monkeypatch.setattr(bot.requests, "get", fake_get)

    with patch("core.voice.stt.transcribe_file", return_value=""):
        text = asyncio.run(bot._transcribe_telegram_voice("file_id_abc"))

    assert text == ""


def test_text_and_voice_commands_only_from_owner(monkeypatch):
    handle, transcribe, send = AsyncMock(), AsyncMock(return_value='Analizza i deploy'), MagicMock()
    monkeypatch.setattr(bot, 'handle', handle)
    monkeypatch.setattr(bot, '_transcribe_telegram_voice', transcribe)
    monkeypatch.setattr(bot, 'send', send)
    async def scenario():
        await bot.handle_telegram_message({'from':{'id':-1},'voice':{'file_id':'unknown'}})
        await bot.handle_telegram_message({'from':{'id':bot.OWNER_ID},'text':'Cosa richiede attenzione?'})
        await bot.handle_telegram_message({'from':{'id':bot.OWNER_ID},'voice':{'file_id':'mine','duration':20}})
        await bot.handle_telegram_message({'from':{'id':bot.OWNER_ID},'voice':{'file_id':'long','duration':181}})
    asyncio.run(scenario())
    assert [c.args[0] for c in handle.await_args_list] == ['Cosa richiede attenzione?', 'Analizza i deploy']
    transcribe.assert_awaited_once_with('mine')
    assert '3 minuti' in send.call_args.args[0]


def test_temporary_voice_removed_after_transcription_failure(monkeypatch):
    response = MagicMock(content=b'ogg')
    response.json.return_value = {'result':{'file_path':'voice/test.ogg'}}
    monkeypatch.setattr(bot.requests, 'get', MagicMock(return_value=response))
    paths = []
    def fail(path):
        paths.append(Path(path))
        raise RuntimeError('trascrizione fallita')
    with patch('core.voice.stt.transcribe_file', side_effect=fail):
        with pytest.raises(RuntimeError):
            asyncio.run(bot._transcribe_telegram_voice('test'))
    assert len(paths) == 1 and not paths[0].exists()


def test_telegram_error_masks_configured_and_url_tokens(monkeypatch):
    from core import telegram
    monkeypatch.setattr(telegram, 'TOKEN', 'fake-secret-token')
    assert 'fake-secret-token' not in telegram.safe_error('URL fake-secret-token/getUpdates')
    assert '123:abc_DEF' not in telegram.safe_error('https://api.telegram.org/bot123:abc_DEF/getUpdates')
