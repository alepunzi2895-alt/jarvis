import asyncio
from unittest.mock import MagicMock, patch

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
