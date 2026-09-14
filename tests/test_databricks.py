import asyncio

import pytest
import requests
from unittest.mock import MagicMock

from core import databricks


@pytest.fixture(autouse=True)
def _qas_env(monkeypatch):
    monkeypatch.setitem(
        databricks._ENVIRONMENTS,
        "qas",
        {"host": "https://qas.example.com", "client_id": "id", "client_secret": "secret", "space_id": "space-123"},
    )
    databricks._token_cache.clear()
    databricks._pending.clear()


def _fake_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def test_get_token_caches_until_near_expiry(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return _fake_response({"access_token": "tok1", "token_type": "Bearer", "expires_in": 3600})

    monkeypatch.setattr(databricks.requests, "post", fake_post)
    assert databricks._get_token("qas") == "tok1"
    assert databricks._get_token("qas") == "tok1"
    assert len(calls) == 1  # il secondo giro viene dalla cache, non da una nuova richiesta


def test_ask_genie_qas_polls_until_completed(monkeypatch):
    get_responses = [
        {"status": "ASKING_AI"},
        {"status": "EXECUTING_QUERY"},
        {
            "status": "COMPLETED",
            "attachments": [{"text": {"content": "42 clienti."}, "query": {"query": "SELECT 1"}}],
        },
    ]

    def fake_post(url, **kwargs):
        if url.endswith("/oidc/v1/token"):
            return _fake_response({"access_token": "tok", "expires_in": 3600})
        return _fake_response({"conversation_id": "c1", "message_id": "m1"})

    monkeypatch.setattr(databricks.requests, "post", fake_post)
    monkeypatch.setattr(databricks.requests, "get", lambda *a, **k: _fake_response(get_responses.pop(0)))
    monkeypatch.setattr(databricks.time, "sleep", lambda s: None)

    answer = databricks.ask_genie_qas("quanti clienti abbiamo?")
    assert "42 clienti" in answer
    assert "SELECT 1" in answer
    assert not get_responses  # ha fatto polling finche' non e' arrivato a COMPLETED


def test_ask_genie_raises_on_failed_status(monkeypatch):
    def fake_post(url, **kwargs):
        if url.endswith("/oidc/v1/token"):
            return _fake_response({"access_token": "tok", "expires_in": 3600})
        return _fake_response({"conversation_id": "c1", "message_id": "m1"})

    monkeypatch.setattr(databricks.requests, "post", fake_post)
    monkeypatch.setattr(databricks.requests, "get", lambda *a, **k: _fake_response({"status": "FAILED"}))

    with pytest.raises(databricks.GenieError):
        databricks.ask_genie_qas("domanda impossibile")


def test_ask_genie_requires_space_id(monkeypatch):
    monkeypatch.setitem(
        databricks._ENVIRONMENTS,
        "qas",
        {"host": "https://qas.example.com", "client_id": "id", "client_secret": "s", "space_id": ""},
    )
    with pytest.raises(databricks.GenieError):
        databricks.ask_genie_qas("qualunque cosa")


def test_ask_genie_requires_credentials():
    with pytest.raises(databricks.GenieError):
        databricks.ask_genie("qualunque cosa", env="ambiente-inesistente")


def test_prd_confirmation_flow(monkeypatch):
    token = databricks.stage_prd_confirmation("genie", "domanda su produzione")
    assert token in databricks._pending

    called = {}

    def fake_ask_genie(question, env="qas"):
        called["question"], called["env"] = question, env
        return "risposta prd"

    monkeypatch.setattr(databricks, "ask_genie", fake_ask_genie)
    answer = databricks.confirm_prd(token)
    assert answer == "risposta prd"
    assert called == {"question": "domanda su produzione", "env": "prd"}
    assert token not in databricks._pending  # consumato, non riutilizzabile


def test_deny_prd_removes_pending():
    token = databricks.stage_prd_confirmation("genie", "x")
    assert databricks.deny_prd(token) is True
    assert databricks.deny_prd(token) is False  # gia' rimosso, seconda deny non trova nulla


def test_confirm_prd_unknown_token_raises():
    with pytest.raises(databricks.GenieError):
        databricks.confirm_prd("non-esiste")


def test_extract_and_execute_only_reaches_qas(monkeypatch):
    calls = []
    monkeypatch.setattr(databricks, "ask_genie_qas", lambda q: calls.append(q) or "risposta")
    text = 'Ecco.\n\n```genie\n{"question": "quanti ordini oggi?"}\n```'
    cleaned = asyncio.run(databricks.extract_and_execute(text))
    assert calls == ["quanti ordini oggi?"]
    assert "```genie" not in cleaned
    assert "risposta" in cleaned


def test_extract_and_execute_no_block_is_noop():
    text = "Nessun blocco qui."
    assert asyncio.run(databricks.extract_and_execute(text)) == text


def test_extract_and_execute_reports_genie_error_without_raising(monkeypatch):
    def boom(q):
        raise databricks.GenieError("spazio non configurato")

    monkeypatch.setattr(databricks, "ask_genie_qas", boom)
    text = '```genie\n{"question": "x"}\n```'
    cleaned = asyncio.run(databricks.extract_and_execute(text))
    assert "spazio non configurato" in cleaned
