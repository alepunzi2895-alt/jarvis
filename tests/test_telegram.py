from unittest.mock import MagicMock

from core import telegram


def test_send_to_owner_noop_when_not_configured(monkeypatch):
    monkeypatch.setattr(telegram, "TOKEN", "")
    monkeypatch.setattr(telegram, "OWNER_ID", "")
    post = MagicMock()
    monkeypatch.setattr(telegram.requests, "post", post)
    telegram.send_to_owner("ciao")
    post.assert_not_called()


def test_send_to_owner_posts_when_configured(monkeypatch):
    monkeypatch.setattr(telegram, "TOKEN", "tok")
    monkeypatch.setattr(telegram, "OWNER_ID", "123")
    monkeypatch.setattr(telegram, "API", "https://api.telegram.org/bottok")
    post = MagicMock()
    monkeypatch.setattr(telegram.requests, "post", post)
    telegram.send_to_owner("ciao Signore")
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "https://api.telegram.org/bottok/sendMessage"
    assert kwargs["json"]["chat_id"] == "123"
    assert kwargs["json"]["text"] == "ciao Signore"


def test_send_to_owner_splits_long_text_into_chunks(monkeypatch):
    monkeypatch.setattr(telegram, "TOKEN", "tok")
    monkeypatch.setattr(telegram, "OWNER_ID", "123")
    monkeypatch.setattr(telegram, "_CHUNK_CHARS", 10)
    post = MagicMock()
    monkeypatch.setattr(telegram.requests, "post", post)
    telegram.send_to_owner("a" * 25)
    assert post.call_count == 3  # 10 + 10 + 5


def test_send_to_owner_swallows_network_errors(monkeypatch):
    monkeypatch.setattr(telegram, "TOKEN", "tok")
    monkeypatch.setattr(telegram, "OWNER_ID", "123")

    def boom(*a, **k):
        raise ConnectionError("rete giu'")

    monkeypatch.setattr(telegram.requests, "post", boom)
    telegram.send_to_owner("ciao")  # non deve sollevare
