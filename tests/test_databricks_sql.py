import asyncio

import pytest
from unittest.mock import MagicMock

from core import databricks


@pytest.fixture(autouse=True)
def _qas_env(monkeypatch):
    monkeypatch.setitem(
        databricks._ENVIRONMENTS,
        "qas",
        {
            "host": "https://qas.example.com",
            "client_id": "id",
            "client_secret": "secret",
            "space_id": "space-123",
            "warehouse_id": "wh-123",
        },
    )
    databricks._token_cache.clear()
    databricks._pending.clear()


def _fake_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM tabella",
        "  select conteggio from x",
        "-- commento\nSELECT 1",
        "SHOW TABLES",
        "DESCRIBE tabella",
        "DESC tabella",
        "EXPLAIN SELECT 1",
        "WITH cte AS (SELECT 1) SELECT * FROM cte",
        "SELECT 1;",
    ],
)
def test_is_read_only_sql_accepts_reads(sql):
    assert databricks._is_read_only_sql(sql) is True


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO tabella VALUES (1)",
        "UPDATE tabella SET x=1",
        "DELETE FROM tabella",
        "DROP TABLE tabella",
        "CREATE TABLE x AS SELECT 1",
        "ALTER TABLE x ADD COLUMN y INT",
        "MERGE INTO x USING y ON ...",
        "SELECT 1; DROP TABLE tabella",  # doppia istruzione, anche se la prima è una SELECT
        "",
    ],
)
def test_is_read_only_sql_rejects_writes(sql):
    assert databricks._is_read_only_sql(sql) is False


def test_run_sql_rejects_write_before_any_network_call(monkeypatch):
    post = MagicMock()
    monkeypatch.setattr(databricks.requests, "post", post)
    with pytest.raises(databricks.SqlError):
        databricks.run_sql_qas("DELETE FROM tabella")
    post.assert_not_called()


def test_run_sql_requires_warehouse_id(monkeypatch):
    monkeypatch.setitem(
        databricks._ENVIRONMENTS,
        "qas",
        {"host": "https://qas.example.com", "client_id": "id", "client_secret": "s", "space_id": "", "warehouse_id": ""},
    )
    with pytest.raises(databricks.SqlError):
        databricks.run_sql_qas("SELECT 1")


def test_run_sql_polls_until_succeeded_and_formats_result(monkeypatch):
    def fake_post(url, **kwargs):
        if url.endswith("/oidc/v1/token"):
            return _fake_response({"access_token": "tok", "expires_in": 3600})
        return _fake_response({"statement_id": "s1", "status": {"state": "PENDING"}})

    get_responses = [
        {"status": {"state": "RUNNING"}},
        {
            "status": {"state": "SUCCEEDED"},
            "manifest": {"schema": {"columns": [{"name": "n"}]}, "total_row_count": 2},
            "result": {"data_array": [["1"], ["2"]]},
        },
    ]

    monkeypatch.setattr(databricks.requests, "post", fake_post)
    monkeypatch.setattr(databricks.requests, "get", lambda *a, **k: _fake_response(get_responses.pop(0)))
    monkeypatch.setattr(databricks.time, "sleep", lambda s: None)

    result = databricks.run_sql_qas("SELECT n FROM tabella")
    assert "1" in result and "2" in result
    assert not get_responses


def test_run_sql_raises_on_failed_status(monkeypatch):
    def fake_post(url, **kwargs):
        if url.endswith("/oidc/v1/token"):
            return _fake_response({"access_token": "tok", "expires_in": 3600})
        return _fake_response({"statement_id": "s1", "status": {"state": "FAILED", "error": {"message": "colonna inesistente"}}})

    monkeypatch.setattr(databricks.requests, "post", fake_post)
    with pytest.raises(databricks.SqlError, match="colonna inesistente"):
        databricks.run_sql_qas("SELECT colonna_inesistente FROM tabella")


def test_sql_prd_confirmation_flow(monkeypatch):
    token = databricks.stage_prd_confirmation("sql", "SELECT 1")
    monkeypatch.setattr(databricks, "run_sql", lambda sql, env: f"risultato di {sql} su {env}")
    answer = databricks.confirm_prd(token)
    assert answer == "risultato di SELECT 1 su prd"


def test_genie_and_sql_confirmations_use_independent_tokens():
    t1 = databricks.stage_prd_confirmation("genie", "domanda")
    t2 = databricks.stage_prd_confirmation("sql", "SELECT 1")
    assert t1 != t2
    assert databricks.deny_prd(t1) is True
    assert databricks.deny_prd(t2) is True


def test_extract_and_execute_handles_dbsql_block(monkeypatch):
    calls = []
    monkeypatch.setattr(databricks, "run_sql_qas", lambda sql: calls.append(sql) or "1 riga")
    text = 'Ecco.\n\n```dbsql\n{"sql": "SELECT 1"}\n```'
    cleaned = asyncio.run(databricks.extract_and_execute(text))
    assert calls == ["SELECT 1"]
    assert "```dbsql" not in cleaned
    assert "1 riga" in cleaned


def test_extract_and_execute_reports_sql_error_without_raising(monkeypatch):
    def boom(sql):
        raise databricks.SqlError("rifiutata")

    monkeypatch.setattr(databricks, "run_sql_qas", boom)
    text = '```dbsql\n{"sql": "DELETE FROM x"}\n```'
    cleaned = asyncio.run(databricks.extract_and_execute(text))
    assert "rifiutata" in cleaned


def test_extract_and_execute_handles_both_genie_and_sql_blocks(monkeypatch):
    monkeypatch.setattr(databricks, "ask_genie_qas", lambda q: "risposta genie")
    monkeypatch.setattr(databricks, "run_sql_qas", lambda sql: "risultato sql")
    text = '```genie\n{"question": "quanti ordini?"}\n```\n\n```dbsql\n{"sql": "SELECT 1"}\n```'
    cleaned = asyncio.run(databricks.extract_and_execute(text))
    assert "risposta genie" in cleaned
    assert "risultato sql" in cleaned
