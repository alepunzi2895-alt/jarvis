import asyncio
import importlib
from datetime import datetime, timedelta

from core import claude_bridge, costs, intents
from core.system_executor import ExecResult
from tests.test_claude_bridge import _FakeBlock, _FakeResponse, _FakeUsage, _patch_common


def test_usd_counts_cache_write_and_read():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    # Sonnet 5: input 2, output 10, scrittura 1,25x, lettura 0,1x
    assert round(costs.usd("claude-sonnet-5", usage), 4) == round(2 + 10 + 2.5 + 0.2, 4)
    assert costs.usd("modello-sconosciuto", usage) == 0


def test_haiku_alias_is_haiku_5_5_with_low_effort():
    assert costs.resolve("haiku") == "claude-haiku-5-5"
    assert costs.resolve("claude-haiku-4-5") == "claude-haiku-4-5"
    assert costs.request_options("claude-haiku-5-5") == {"output_config": {"effort": "low"}}
    # Haiku 4.5 rifiuta effort; Sonnet resta sul default del modello.
    assert costs.request_options("claude-haiku-4-5") == {}
    assert costs.request_options("claude-sonnet-5") == {}


def test_record_and_summary_use_local_ledger():
    usage = _FakeUsage(input_tokens=1000, output_tokens=100)
    cost = costs.record("text", "claude-sonnet-5", usage)
    costs.record("cli", "haiku", {}, cost=0.05)
    data = costs.summary()
    assert round(data["today"], 6) == round(cost + 0.05, 6)
    assert {row["channel"] for row in data["by_model"]} == {"text", "cli"}
    assert "oggi $" in costs.format_summary(data)


def test_old_calls_do_not_count_today(monkeypatch):
    costs.record("text", "claude-sonnet-5", {"output_tokens": 1_000_000})
    assert costs.spent(datetime.now() + timedelta(minutes=1)) == 0


def test_empty_ledger_summary():
    assert "Nessuna spesa" in costs.format_summary()


def test_daily_budget_blocks_api_call(monkeypatch):
    monkeypatch.setattr(costs, "DAILY_BUDGET", 0.01)
    costs.record("text", "claude-sonnet-5", {"output_tokens": 10_000})  # 0,10 USD
    _patch_common(monkeypatch, [])  # nessuna risposta: una chiamata farebbe IndexError
    text, _sid, cost = asyncio.run(claude_bridge._run_claude_api("ciao", "jarvis", "C:\\ws", None, "text"))
    assert "tetto di spesa giornaliero" in text
    assert cost == 0


def test_daily_budget_zero_means_off(monkeypatch):
    monkeypatch.setattr(costs, "DAILY_BUDGET", 0.0)
    costs.record("text", "claude-sonnet-5", {"output_tokens": 1_000_000})
    assert costs.budget_block() is None


def test_request_budget_stops_tool_loop(monkeypatch):
    monkeypatch.setattr(costs, "REQUEST_BUDGET", 0.05)
    tool_call = _FakeBlock("tool_use", id="t1", name="list_dir", input={"path": "."})
    expensive = _FakeUsage(input_tokens=30_000, output_tokens=1_000)  # ~0,07 USD su Sonnet 5
    responses = [_FakeResponse([tool_call], "tool_use", expensive) for _ in range(5)]
    _patch_common(monkeypatch, responses)
    monkeypatch.setattr(claude_bridge._system_executor, "list_dir", lambda p: ExecResult(ok=True, stdout="a.py"))
    text, _sid, cost = asyncio.run(claude_bridge._run_claude_api(
        "loop", "jarvis", "C:\\ws", None, "text", model="claude-sonnet-5"))
    assert "tetto di spesa" in text
    assert round(cost, 4) == 0.07  # una sola chiamata pagata, niente secondo giro
    assert costs.summary()["today"] == cost


def test_refusal_without_text_gets_clear_message(monkeypatch):
    _patch_common(monkeypatch, [_FakeResponse([], "refusal")])
    text, _sid, _cost = asyncio.run(claude_bridge._run_claude_api("x", "jarvis", "C:\\ws", None, "text"))
    assert text == "Non posso aiutarti con questa richiesta."


def test_api_request_sends_effort_only_for_haiku_5_5(monkeypatch):
    sent = []
    _patch_common(monkeypatch, [])

    class Messages:
        async def create(self, **kwargs):
            sent.append(kwargs)
            return _FakeResponse([_FakeBlock("text", text="Ok.")], "end_turn")

    class Client:
        messages = Messages()

    monkeypatch.setattr(claude_bridge, "_get_api_client", lambda: Client())
    for model in ("claude-haiku-5-5", "claude-sonnet-5"):
        asyncio.run(claude_bridge._run_claude_api("ciao", "jarvis", "C:\\ws", None, "text", model=model))
    assert sent[0]["output_config"] == {"effort": "low"}
    assert "output_config" not in sent[1]


def test_costs_intent_needs_llm_reference():
    assert intents.parse_intent("quanto spendo di API?") == {"type": "costs"}
    assert intents.parse_intent("quanto mi costa jarvis") == {"type": "costs"}
    # Domanda finanziaria generica: resta al modello (futuro coach finanziario).
    assert intents.parse_intent("quanto ho speso questo mese") is None


def test_costs_intent_reads_ledger():
    costs.record("text", "claude-sonnet-5", {"output_tokens": 1000})
    text = intents._execute({"type": "costs"}, None, voice=False)
    assert text.startswith("Spesa LLM stimata")


def test_web_queue_is_off_unless_enabled(monkeypatch):
    from core import turso, web_bridge
    monkeypatch.setattr(turso, "ENABLED", True)
    monkeypatch.delenv("JARVIS_WEB_QUEUE", raising=False)
    try:
        assert importlib.reload(web_bridge).ENABLED is False
        monkeypatch.setenv("JARVIS_WEB_QUEUE", "1")
        assert importlib.reload(web_bridge).ENABLED is True
    finally:
        monkeypatch.delenv("JARVIS_WEB_QUEUE", raising=False)
        importlib.reload(web_bridge)
