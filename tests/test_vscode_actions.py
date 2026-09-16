import asyncio
import json
import subprocess
from unittest.mock import MagicMock, patch

from core import vscode_actions


def test_resolve_project_path_known_workspace(monkeypatch):
    monkeypatch.setattr("core.claude_bridge.WORKSPACES", {"aura": "C:\\Progetti\\aura"})
    monkeypatch.setattr(vscode_actions.executor, "_in_whitelist", lambda p: True)
    assert vscode_actions.resolve_project_path("AURA") == "C:\\Progetti\\aura"


def test_resolve_project_path_unknown_project(monkeypatch):
    monkeypatch.setattr("core.claude_bridge.WORKSPACES", {"aura": "C:\\Progetti\\aura"})
    assert vscode_actions.resolve_project_path("nonexistent") is None


def test_resolve_project_path_rejects_outside_whitelist(monkeypatch):
    monkeypatch.setattr("core.claude_bridge.WORKSPACES", {"aura": "C:\\Progetti\\aura"})
    monkeypatch.setattr(vscode_actions.executor, "_in_whitelist", lambda p: False)
    assert vscode_actions.resolve_project_path("aura") is None


def test_extract_and_execute_no_block_returns_text_unchanged():
    text = "Nessun blocco qui."
    assert asyncio.run(vscode_actions.extract_and_execute(text)) == text


def test_extract_and_execute_opens_vscode_and_starts_background_task():
    text = 'Ecco.\n\n```vscode\n{"project":"aura","prompt":"sistema il bug X"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\\Progetti\\aura") as resolve,
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=True)) as open_vscode,
        patch("core.vscode_actions.start_claude_code_task") as start_task,
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text))

    resolve.assert_called_once_with("aura")
    open_vscode.assert_called_once_with("C:\\Progetti\\aura")
    start_task.assert_called_once_with("aura", "C:\\Progetti\\aura", "sistema il bug X")
    assert "```vscode" not in result
    assert "aggiorno su Telegram" in result


def test_extract_and_execute_without_prompt_only_opens_vscode():
    text = '```vscode\n{"project":"aura"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\\Progetti\\aura"),
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=True)),
        patch("core.vscode_actions.start_claude_code_task") as start_task,
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text))

    start_task.assert_not_called()
    assert "Telegram" not in result


def test_extract_and_execute_unauthorized_project_reports_and_skips():
    text = '```vscode\n{"project":"chissache","prompt":"fai qualcosa"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value=None),
        patch("core.vscode_actions.start_claude_code_task") as start_task,
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text))

    start_task.assert_not_called()
    assert "non riconosciuto" in result.lower()


def test_extract_and_execute_reports_vscode_open_failure():
    text = '```vscode\n{"project":"aura","prompt":"x"}\n```'
    with (
        patch("core.vscode_actions.resolve_project_path", return_value="C:\\Progetti\\aura"),
        patch.object(vscode_actions.executor, "open_vscode", return_value=MagicMock(ok=False, stderr="boom")),
        patch("core.vscode_actions.start_claude_code_task") as start_task,
    ):
        result = asyncio.run(vscode_actions.extract_and_execute(text))

    assert "boom" in result
    # anche se VS Code non si apre, il task di Claude Code parte comunque:
    # e' un problema di visualizzazione, non deve bloccare il lavoro reale.
    start_task.assert_called_once()


def test_extract_and_execute_ignores_malformed_json():
    text = "```vscode\nnon e' json\n```"
    result = asyncio.run(vscode_actions.extract_and_execute(text))
    assert "```vscode" not in result


def test_run_claude_code_background_success(monkeypatch):
    fake_proc = MagicMock(returncode=0, stdout=json.dumps({"result": "fatto!"}), stderr="")
    monkeypatch.setattr(vscode_actions.subprocess, "run", lambda *a, **k: fake_proc)
    sent = []
    monkeypatch.setattr(vscode_actions.telegram, "send_to_owner", lambda text, *a, **k: sent.append(text))

    vscode_actions._run_claude_code_background("aura", "C:\\Progetti\\aura", "fai qualcosa")

    assert len(sent) == 1
    assert "fatto!" in sent[0]
    assert "✅" in sent[0]


def test_run_claude_code_background_reports_failure(monkeypatch):
    fake_proc = MagicMock(returncode=1, stdout="", stderr="errore grave")
    monkeypatch.setattr(vscode_actions.subprocess, "run", lambda *a, **k: fake_proc)
    sent = []
    monkeypatch.setattr(vscode_actions.telegram, "send_to_owner", lambda text, *a, **k: sent.append(text))

    vscode_actions._run_claude_code_background("aura", "C:\\Progetti\\aura", "fai qualcosa")

    assert "errore grave" in sent[0]
    assert "❌" in sent[0]


def test_run_claude_code_background_handles_timeout(monkeypatch):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1800)

    monkeypatch.setattr(vscode_actions.subprocess, "run", fake_run)
    sent = []
    monkeypatch.setattr(vscode_actions.telegram, "send_to_owner", lambda text, *a, **k: sent.append(text))

    vscode_actions._run_claude_code_background("aura", "C:\\Progetti\\aura", "fai qualcosa")

    assert "❌" in sent[0]


def test_run_claude_code_background_falls_back_to_raw_stdout_on_bad_json(monkeypatch):
    fake_proc = MagicMock(returncode=0, stdout="testo non json", stderr="")
    monkeypatch.setattr(vscode_actions.subprocess, "run", lambda *a, **k: fake_proc)
    sent = []
    monkeypatch.setattr(vscode_actions.telegram, "send_to_owner", lambda text, *a, **k: sent.append(text))

    vscode_actions._run_claude_code_background("aura", "C:\\Progetti\\aura", "fai qualcosa")

    assert "testo non json" in sent[0]
