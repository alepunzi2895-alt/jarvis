import pytest

from core import myfxbook


def _account(**overrides):
    defaults = dict(name="MFKK", balance=10000.0, equity=10500.0, gain=5.0, drawdown=2.0, profit=500.0, won_trades=7, lost_trades=3)
    defaults.update(overrides)
    return myfxbook.AccountSnapshot(**defaults)


def test_login_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr(myfxbook, "ENABLED", False)
    with pytest.raises(myfxbook.MyfxbookError):
        myfxbook._login()


def test_get_raises_myfxbook_error_on_error_flag(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "true", "message": "Sessione scaduta"}

    monkeypatch.setattr(myfxbook.requests, "get", lambda *a, **k: FakeResponse())
    with pytest.raises(myfxbook.MyfxbookError, match="Sessione scaduta"):
        myfxbook._get("/whatever.json")


def test_get_accounts_sync_logs_in_and_out(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_get(url, timeout=None):
        calls.append(url)
        if "login.json" in url:
            return FakeResponse({"error": False, "session": "sess123"})
        if "get-my-accounts.json" in url:
            return FakeResponse({
                "error": False,
                "accounts": [
                    {"name": "MFKK", "balance": 10000, "equity": 10500, "gain": 5, "drawdown": 2, "profit": 500, "wonTrades": 7, "lostTrades": 3}
                ],
            })
        if "logout.json" in url:
            return FakeResponse({"error": False})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(myfxbook, "ENABLED", True)
    monkeypatch.setattr(myfxbook, "EMAIL", "a@b.com")
    monkeypatch.setattr(myfxbook, "PASSWORD", "pw")
    monkeypatch.setattr(myfxbook.requests, "get", fake_get)

    accounts = myfxbook.get_accounts_sync()

    assert len(accounts) == 1
    assert accounts[0].name == "MFKK"
    assert accounts[0].equity == 10500.0
    assert any("login.json" in c for c in calls)
    assert any("logout.json" in c for c in calls)


def test_format_accounts_empty_list():
    assert "Nessun" in myfxbook.format_accounts([], voice=False)
    assert "Signore" in myfxbook.format_accounts([], voice=True)


def test_format_accounts_voice_mentions_equity_and_gain():
    text = myfxbook.format_accounts([_account()], voice=True)
    assert "MFKK" in text and "10500" in text and "Signore" in text


def test_format_accounts_text_includes_winrate():
    text = myfxbook.format_accounts([_account()], voice=False)
    assert "MFKK" in text
    assert "70%" in text  # 7 vinti su 10 totali
