from unittest.mock import patch

from core import brain


def test_log_interaction_upserts_a_per_day_node():
    with patch("core.turso.execute_batch") as batch, patch("core.turso.execute") as execute:
        execute.return_value = [{"id": "abc123"}]
        brain.log_interaction("che ore sono?", "jarvis", "voice")

    batch.assert_called_once()  # bootstrap tabelle
    insert_sql, insert_args = execute.call_args_list[0].args
    assert "INSERT INTO brain_nodes" in insert_sql
    assert "Interazioni jarvis" in insert_args[1]  # label
    assert "che ore sono?" in insert_args[3]  # summary contiene lo snippet
    assert "voice" in insert_args[5]  # tags


def test_log_interaction_truncates_long_prompts():
    long_prompt = "a" * 500
    with patch("core.turso.execute_batch"), patch("core.turso.execute", return_value=[{"id": "x"}]) as execute:
        brain.log_interaction(long_prompt, "jarvis", "text")

    insert_args = execute.call_args_list[0].args[1]
    assert len(insert_args[3]) < 200


def test_log_interaction_never_raises_on_turso_error():
    with patch("core.turso.execute_batch", side_effect=RuntimeError("turso down")):
        brain.log_interaction("test", "jarvis", "text")  # non deve sollevare


def test_extract_and_store_strips_block_even_if_bootstrap_fails():
    text = 'risposta utile\n```brain\n{"nodes":[{"label":"x"}]}\n```'
    with patch("core.brain._bootstrap", side_effect=RuntimeError("turso down")):
        cleaned = brain.extract_and_store(text, "jarvis")
    assert "```brain" not in cleaned
    assert "risposta utile" in cleaned


def test_extract_and_store_survives_a_single_bad_node_and_processes_the_rest():
    text = (
        'ok\n```brain\n{"nodes":[{"label":"a"}]}\n```\n'
        'ancora\n```brain\n{"nodes":[{"label":"b"}]}\n```'
    )
    with patch("core.brain._bootstrap"), patch("core.brain._store", side_effect=[RuntimeError("boom"), None]) as store:
        cleaned = brain.extract_and_store(text, "jarvis")
    assert store.call_count == 2
    assert "```brain" not in cleaned


def test_fetch_context_returns_empty_string_on_turso_error():
    with patch("core.brain._bootstrap", side_effect=RuntimeError("turso down")):
        assert brain.fetch_context("jarvis") == ""


def test_fetch_context_excludes_interaction_log_nodes_from_the_query():
    with patch("core.brain._bootstrap"), patch("core.turso.execute", return_value=[]) as execute:
        brain.fetch_context("jarvis")
    sql = execute.call_args_list[0].args[0]
    assert "NOT LIKE '%interazione%'" in sql


def test_fetch_context_returns_empty_string_when_no_nodes():
    with patch("core.brain._bootstrap"), patch("core.turso.execute", return_value=[]):
        assert brain.fetch_context("jarvis") == ""
