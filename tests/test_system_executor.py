from unittest.mock import patch, MagicMock

import pytest

from core.obsidian import ObsidianVault
from core.system_executor import SystemExecutor


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    return ObsidianVault(root)


@pytest.fixture
def allowed_dir(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    return d


@pytest.fixture
def executor(allowed_dir, vault):
    return SystemExecutor(allowed_dirs=[allowed_dir], vault=vault)


def _fake_proc(returncode=0, stdout="ok", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_whitelisted_command_executes_without_confirmation(executor, allowed_dir):
    with patch("core.system_executor.subprocess.run", return_value=_fake_proc()) as run:
        result = executor.run("git status", cwd=allowed_dir)
    assert result.ok is True
    assert result.needs_confirmation is False
    run.assert_called_once()


def test_command_outside_whitelist_needs_confirmation(executor, allowed_dir):
    with patch("core.system_executor.subprocess.run") as run:
        result = executor.run("Remove-Item foo.txt", cwd=allowed_dir)
    assert result.needs_confirmation is True
    assert result.token is not None
    run.assert_not_called()


def test_directory_outside_whitelist_always_needs_confirmation(executor, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with patch("core.system_executor.subprocess.run") as run:
        result = executor.run("git status", cwd=outside)
    assert result.needs_confirmation is True
    run.assert_not_called()


def test_git_push_requires_confirmation_even_though_git_allowed(executor, allowed_dir):
    with patch("core.system_executor.subprocess.run") as run:
        result = executor.run("git push", cwd=allowed_dir)
    assert result.needs_confirmation is True
    run.assert_not_called()


def test_path_traversal_outside_whitelist_needs_confirmation(executor, allowed_dir):
    with patch("core.system_executor.subprocess.run") as run:
        result = executor.run(r"Get-Content ..\..\secret.txt", cwd=allowed_dir)
    assert result.needs_confirmation is True
    run.assert_not_called()


def test_confirm_executes_pending_action(executor, allowed_dir):
    with patch("core.system_executor.subprocess.run") as run:
        staged = executor.run("Remove-Item foo.txt", cwd=allowed_dir)
    assert staged.needs_confirmation is True

    with patch("core.system_executor.subprocess.run", return_value=_fake_proc()) as run:
        result = executor.confirm(staged.token)
    assert result.ok is True
    run.assert_called_once()


def test_deny_discards_pending_action(executor, allowed_dir):
    with patch("core.system_executor.subprocess.run"):
        staged = executor.run("Remove-Item foo.txt", cwd=allowed_dir)

    assert executor.deny(staged.token) is True

    result = executor.confirm(staged.token)
    assert result.ok is False
    assert "non valido" in result.stderr.lower()


def test_execution_logged_to_vault(executor, allowed_dir, vault):
    with patch("core.system_executor.subprocess.run", return_value=_fake_proc()):
        executor.run("git status", cwd=allowed_dir)

    from datetime import date

    log = vault.read_note(f"Logs/system-{date.today().isoformat()}")
    assert "git status" in log


def test_open_app_from_registry(executor):
    with patch(
        "core.system_executor._resolve_app_path",
        return_value=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ), patch("core.system_executor.subprocess.Popen") as popen:
        result = executor.open_app("chrome")
    assert result.ok is True
    popen.assert_called_once_with([r"C:\Program Files\Google\Chrome\Application\chrome.exe"])


def test_open_app_not_found(executor):
    with patch("core.system_executor._resolve_app_path", return_value=None):
        result = executor.open_app("app-inesistente")
    assert result.ok is False


def test_open_app_from_registry_alias(executor):
    with patch("core.system_executor.subprocess.Popen") as popen:
        result = executor.open_app("notepad")
    assert result.ok is True
    popen.assert_called_once_with(["notepad.exe"])
