import asyncio
from unittest.mock import MagicMock, patch

from core import vscode_actions


def test_resolve_project_path_known_workspace(monkeypatch):
    monkeypatch.setattr("core.claude_bridge.WORKSPACES", {"aura": "C:\Progetti\aura"})
    monkeypatch.setattr(vscode_actions.executor, "_in_whitelist", lambda p: True)
    assert vscode_actions.resolve_project_path("AURA") == "C:\Progetti\aura"


def test_resolve_project_path_unknown_project(monkeypatch):
    monkeypatch.setattr("core.claude_bridge.WORKSPACES", {"aura": "C:\Progetti\aura"})
    assert vscode_actions.resolve_project_path("nonexistent") is None


def test_resolve_project_path_rejects_outside_whitelist(monkeypatch):
    monkeypatch.setattr("core.claude_bridge.WORKSPACES", {"aura": "C:\Progetti\aura"})
    monkeypatch.setattr(vscode_actions.executor, "_in_whitelist", lambda p: False)
    assert vscode_actions.resolve_project_path("aura") is None


def test_extract_and_execute_no_block_returns_text_unchanged():
    text = "Nessun blocco qui."
    assert asyncio.run(vscode_actions.extract_and_execute(text)) == text


def test_extract_and_execute_opens_vscode_and_delegates_tracked_edit():
    text = 'Ecco.\n\n```vscode\n{"project":"aura","prompt":"sistema il bug X"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\Progetti\aura"),
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=True)) as open_vscode,
        patch("core.coding_tasks.start_task", return_value={"job_id": "abc123"}) as start,
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text, channel="voice"))

    open_vscode.assert_called_once_with("C:\Progetti\aura")
    start.assert_called_once_with("claude", "aura", "sistema il bug X", mode="edit", explicit=True, channel="voice")
    assert "```vscode" not in result
    assert "abc123" in result


def test_extract_and_execute_passes_read_mode():
    text = '```vscode\n{"project":"aura","prompt":"analizza","mode":"read"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\Progetti\aura"),
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=True)),
        patch("core.coding_tasks.start_task", return_value={"job_id": "x"}) as start,
    ):
        asyncio.run(vscode_actions.extract_and_execute(text))
    assert start.call_args.kwargs["mode"] == "read"


def test_extract_and_execute_without_prompt_only_opens_vscode():
    text = '```vscode\n{"project":"aura"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\Progetti\aura"),
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=True)),
        patch("core.coding_tasks.start_task") as start,
    ):
        asyncio.run(vscode_actions.extract_and_execute(text))
    start.assert_not_called()


def test_extract_and_execute_unauthorized_project_reports_and_skips():
    text = '```vscode\n{"project":"chissache","prompt":"fai qualcosa"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value=None),
        patch("core.coding_tasks.start_task") as start,
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text))
    start.assert_not_called()
    assert "non riconosciuto" in result.lower()


def test_extract_and_execute_reports_vscode_open_failure_and_still_delegates():
    text = '```vscode\n{"project":"aura","prompt":"x"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\Progetti\aura"),
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=False, stderr="boom")),
        patch("core.coding_tasks.start_task", return_value={"job_id": "j"}) as start,
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text))
    assert "boom" in result
    start.assert_called_once()


def test_delegation_refusal_is_reported_not_raised():
    text = '```vscode\n{"project":"aura","prompt":"x"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\Progetti\aura"),
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=True)),
        patch("core.coding_tasks.start_task", side_effect=ValueError("Cartella in sola lettura")),
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text))
    assert "sola lettura" in result


def test_extract_and_execute_ignores_malformed_json():
    text = "```vscode\nnon e' json\n```"
    result = asyncio.run(vscode_actions.extract_and_execute(text))
    assert "```vscode" not in result
