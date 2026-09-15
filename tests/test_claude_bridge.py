import asyncio
from unittest.mock import MagicMock

import pytest

from core import claude_bridge
from core.system_executor import ExecResult


# --------------------------------------------------------------------------- _execute_tool / _resolve_in_workspace


def test_resolve_in_workspace_relative_path():
    assert claude_bridge._resolve_in_workspace("foo.py", "C:\\ws") == str(__import__("pathlib").Path("C:\\ws\\foo.py"))


def test_resolve_in_workspace_absolute_path_untouched():
    assert claude_bridge._resolve_in_workspace("C:\\other\\foo.py", "C:\\ws") == "C:\\other\\foo.py"


def test_execute_tool_read_file_ok(monkeypatch):
    monkeypatch.setattr(claude_bridge._system_executor, "read_file", lambda p: ExecResult(ok=True, stdout="contenuto"))
    text, is_error = claude_bridge._execute_tool("read_file", {"path": "a.py"}, "C:\\ws")
    assert text == "contenuto"
    assert is_error is False


def test_execute_tool_write_file_ok(monkeypatch):
    monkeypatch.setattr(claude_bridge._system_executor, "write_file", lambda p, c: ExecResult(ok=True))
    text, is_error = claude_bridge._execute_tool("write_file", {"path": "a.py", "content": "x"}, "C:\\ws")
    assert "scritto" in text.lower()
    assert is_error is False


def test_execute_tool_needs_confirmation_tells_user_the_token(monkeypatch):
    monkeypatch.setattr(
        claude_bridge._system_executor, "run", lambda cmd, cwd: ExecResult(ok=False, needs_confirmation=True, token="abc123")
    )
    text, is_error = claude_bridge._execute_tool("run_command", {"command": "git push"}, "C:\\ws")
    assert "abc123" in text
    assert "/confirm" in text
    assert is_error is False  # non e' un errore: Claude deve solo riferirlo, non ritentare


def test_execute_tool_error_result_is_flagged(monkeypatch):
    monkeypatch.setattr(claude_bridge._system_executor, "read_file", lambda p: ExecResult(ok=False, stderr="non trovato"))
    text, is_error = claude_bridge._execute_tool("read_file", {"path": "assente.py"}, "C:\\ws")
    assert "non trovato" in text
    assert is_error is True


def test_execute_tool_unknown_name():
    text, is_error = claude_bridge._execute_tool("delete_everything", {}, "C:\\ws")
    assert is_error is True
    assert "sconosciuto" in text.lower()


def test_execute_tool_swallows_unexpected_exceptions(monkeypatch):
    def _boom(p):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(claude_bridge._system_executor, "read_file", _boom)
    text, is_error = claude_bridge._execute_tool("read_file", {"path": "a.py"}, "C:\\ws")
    assert is_error is True
    assert "kaboom" in text


def test_truncate_tool_result_leaves_short_text_untouched():
    assert claude_bridge._truncate_tool_result("breve") == "breve"


def test_truncate_tool_result_truncates_long_text():
    long_text = "x" * (claude_bridge.MAX_TOOL_RESULT_CHARS + 500)
    result = claude_bridge._truncate_tool_result(long_text)
    assert len(result) < len(long_text)
    assert "troncato" in result


# --------------------------------------------------------------------------- _trim_history


def test_trim_history_keeps_last_n_pairs():
    history = [{"role": "user", "content": str(i)} for i in range(50)]
    trimmed = claude_bridge._trim_history(history)
    assert len(trimmed) == claude_bridge.MAX_HISTORY_TURNS * 2
    assert trimmed[-1]["content"] == "49"


def test_trim_history_shorter_than_cap_untouched():
    history = [{"role": "user", "content": "1"}, {"role": "assistant", "content": "2"}]
    assert claude_bridge._trim_history(history) == history


# --------------------------------------------------------------------------- _run_claude_api (loop agentic manuale)


class _FakeUsage:
    def __init__(self, input_tokens=10, output_tokens=5):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeBlock:
    def __init__(self, type_, **fields):
        self.type = type_
        self._fields = fields
        for k, v in fields.items():
            setattr(self, k, v)

    def model_dump(self):
        return {"type": self.type, **self._fields}


class _FakeResponse:
    def __init__(self, content, stop_reason, usage=None):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage or _FakeUsage()


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **kwargs):
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


async def _identity_async(text, *_args, **_kwargs):
    return text


def _patch_common(monkeypatch, responses, state=None):
    monkeypatch.setattr(claude_bridge, "_get_api_client", lambda: _FakeClient(responses))
    monkeypatch.setattr(claude_bridge, "_build_context_prefix", lambda ws: _identity_async("SYSTEM"))
    monkeypatch.setattr(claude_bridge, "_run_post_processing", lambda text, ws, prompt, channel: _identity_async(text))
    monkeypatch.setattr(claude_bridge, "save_state", lambda s: None)
    monkeypatch.setattr(claude_bridge, "state", state or {"ws": "jarvis", "sessions": {}, "api_sessions": {}})


def test_run_claude_api_answers_directly_without_tools(monkeypatch):
    _patch_common(monkeypatch, [_FakeResponse([_FakeBlock("text", text="Ciao Alessandro.")], "end_turn")])

    text, sid, cost = asyncio.run(claude_bridge._run_claude_api("ciao", "jarvis", "C:\\ws", None, "text"))

    assert text == "Ciao Alessandro."
    assert sid is None
    assert cost > 0


def test_run_claude_api_executes_tool_then_answers(monkeypatch):
    tool_call = _FakeBlock("tool_use", id="tool_1", name="read_file", input={"path": "memory/profile.md"})
    responses = [
        _FakeResponse([tool_call], "tool_use"),
        _FakeResponse([_FakeBlock("text", text="Ho letto il profilo.")], "end_turn"),
    ]
    _patch_common(monkeypatch, responses)
    monkeypatch.setattr(claude_bridge._system_executor, "read_file", lambda p: ExecResult(ok=True, stdout="Alessandro..."))

    text, _sid, _cost = asyncio.run(claude_bridge._run_claude_api("leggi il profilo", "jarvis", "C:\\ws", None, "text"))

    assert text == "Ho letto il profilo."


def test_run_claude_api_persists_clean_history_across_calls(monkeypatch):
    shared_state = {"ws": "jarvis", "sessions": {}, "api_sessions": {}}
    _patch_common(monkeypatch, [_FakeResponse([_FakeBlock("text", text="Prima risposta.")], "end_turn")], state=shared_state)

    asyncio.run(claude_bridge._run_claude_api("primo messaggio", "jarvis", "C:\\ws", None, "text"))

    history = shared_state["api_sessions"]["jarvis"]
    assert history == [
        {"role": "user", "content": "primo messaggio"},
        {"role": "assistant", "content": "Prima risposta."},
    ]


def test_run_claude_api_gives_up_after_max_tool_turns(monkeypatch):
    tool_call = _FakeBlock("tool_use", id="tool_1", name="list_dir", input={"path": "."})
    # sempre tool_use, non chiude mai il turno da solo
    responses = [_FakeResponse([tool_call], "tool_use") for _ in range(claude_bridge.MAX_TOOL_TURNS)]
    _patch_common(monkeypatch, responses)
    monkeypatch.setattr(claude_bridge._system_executor, "list_dir", lambda p: ExecResult(ok=True, stdout="a.py"))

    text, _sid, _cost = asyncio.run(claude_bridge._run_claude_api("loop infinito", "jarvis", "C:\\ws", None, "text"))

    assert "troppi passaggi" in text.lower() or "mi fermo" in text.lower()


# --------------------------------------------------------------------------- dispatcher run_claude()


def test_run_claude_routes_trading_workspace_to_cli(monkeypatch):
    monkeypatch.setattr(claude_bridge, "state", {"ws": "jarvis", "sessions": {}, "api_sessions": {}})
    called = {}

    async def _fake_cli(prompt, ws, cwd, image_b64, channel):
        called["engine"] = "cli"
        return "ok", "sid", 0.0

    async def _fake_api(prompt, ws, cwd, image_b64, channel):
        called["engine"] = "api"
        return "ok", None, 0.0

    monkeypatch.setattr(claude_bridge, "_run_claude_cli", _fake_cli)
    monkeypatch.setattr(claude_bridge, "_run_claude_api", _fake_api)

    asyncio.run(claude_bridge.run_claude("qualsiasi", ws="trading"))

    assert called["engine"] == "cli"


def test_run_claude_routes_other_workspaces_to_api(monkeypatch):
    monkeypatch.setattr(claude_bridge, "state", {"ws": "jarvis", "sessions": {}, "api_sessions": {}})
    called = {}

    async def _fake_cli(prompt, ws, cwd, image_b64, channel):
        called["engine"] = "cli"
        return "ok", "sid", 0.0

    async def _fake_api(prompt, ws, cwd, image_b64, channel):
        called["engine"] = "api"
        return "ok", None, 0.0

    monkeypatch.setattr(claude_bridge, "_run_claude_cli", _fake_cli)
    monkeypatch.setattr(claude_bridge, "_run_claude_api", _fake_api)

    asyncio.run(claude_bridge.run_claude("qualsiasi", ws="jarvis"))

    assert called["engine"] == "api"


def test_run_claude_respects_cli_fallback_toggle(monkeypatch):
    monkeypatch.setattr(claude_bridge, "state", {"ws": "jarvis", "sessions": {}, "api_sessions": {}})
    monkeypatch.setattr(claude_bridge, "TEXT_ENGINE", "cli")
    called = {}

    async def _fake_cli(prompt, ws, cwd, image_b64, channel):
        called["engine"] = "cli"
        return "ok", "sid", 0.0

    monkeypatch.setattr(claude_bridge, "_run_claude_cli", _fake_cli)

    asyncio.run(claude_bridge.run_claude("qualsiasi", ws="jarvis"))

    assert called["engine"] == "cli"
