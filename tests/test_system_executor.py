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


@pytest.mark.parametrize("cmd", ["git checkout -b feature/x", "git switch main", "git merge feature/x"])
def test_git_local_branch_ops_execute_without_confirmation(executor, allowed_dir, cmd):
    # Ampliato per il motore agentic via API diretta (core/claude_bridge.py):
    # senza, ogni branch/merge in locale avrebbe chiesto conferma manuale.
    # git push resta escluso apposta (vedi test sopra) - invariato.
    with patch("core.system_executor.subprocess.run", return_value=_fake_proc()) as run:
        result = executor.run(cmd, cwd=allowed_dir)
    assert result.ok is True
    assert result.needs_confirmation is False
    run.assert_called_once()


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
    # "firefox" non e' tra gli alias diretti di APP_REGISTRY: deve passare
    # dalla risoluzione dinamica via App Paths di Windows.
    with patch(
        "core.system_executor._resolve_app_path",
        return_value=r"C:\Program Files\Mozilla Firefox\firefox.exe",
    ), patch("core.system_executor.subprocess.Popen") as popen:
        result = executor.open_app("firefox")
    assert result.ok is True
    popen.assert_called_once_with([r"C:\Program Files\Mozilla Firefox\firefox.exe"])


def test_open_app_not_found(executor):
    with patch("core.system_executor._resolve_app_path", return_value=None):
        result = executor.open_app("app-inesistente")
    assert result.ok is False


def test_open_app_from_registry_alias(executor):
    with patch("core.system_executor.subprocess.Popen") as popen:
        result = executor.open_app("notepad")
    assert result.ok is True
    popen.assert_called_once_with(["notepad.exe"])


def test_open_app_brings_window_to_foreground(executor):
    """"quando mi apri altre app mettile in primo piano" (2026-09-15): non
    basta lanciarle, la finestra deve passare davvero in primo piano —
    verificato che open_app avvii il meccanismo con il PID giusto (il
    meccanismo stesso, EnumWindows + AttachThreadInput, e' stato verificato
    a parte dal vivo contro un'app reale, non solo mockato qui)."""
    fake_proc = MagicMock()
    fake_proc.pid = 4242
    seen_pids = []

    def fake_bring_to_foreground(pid):
        seen_pids.append(pid)

    with patch("core.system_executor.subprocess.Popen", return_value=fake_proc), \
         patch("core.system_executor._bring_to_foreground_bg", fake_bring_to_foreground):
        result = executor.open_app("notepad")

    assert result.ok is True
    assert seen_pids == [4242]


def test_bring_to_foreground_bg_never_raises_on_bad_pid():
    """Un PID inesistente/gia' morto (finestra chiusa subito, app fallita ad
    avviarsi, ecc.) non deve mai far esplodere il thread in background —
    silenziosamente rinuncia a portare in primo piano, l'apertura dell'app
    resta comunque riuscita."""
    from core.system_executor import _bring_to_foreground_bg

    thread_ref = {}
    orig_thread = __import__("threading").Thread

    def _capture_thread(*a, **k):
        t = orig_thread(*a, **k)
        thread_ref["t"] = t
        return t

    with patch("threading.Thread", side_effect=_capture_thread):
        _bring_to_foreground_bg(999_999_999)  # PID quasi certamente inesistente

    thread_ref["t"].join(timeout=5)
    assert not thread_ref["t"].is_alive()


def _fake_process(name):
    proc = MagicMock()
    proc.info = {"name": name}
    return proc


def test_close_app_terminates_matching_processes(executor):
    procs = [_fake_process("chrome.exe"), _fake_process("chrome.exe"), _fake_process("notepad.exe")]
    with patch("core.system_executor.psutil.process_iter", return_value=procs):
        result = executor.close_app("chrome")
    assert result.ok is True
    assert procs[0].terminate.called and procs[1].terminate.called
    assert not procs[2].terminate.called


def test_close_app_not_running(executor):
    with patch("core.system_executor.psutil.process_iter", return_value=[]):
        result = executor.close_app("chrome")
    assert result.ok is False


def test_volume_sends_media_key(executor):
    with patch("core.system_executor.subprocess.run", return_value=_fake_proc()) as run:
        result = executor.volume("up")
    assert result.ok is True
    assert "175" in run.call_args[0][0][-1]


def test_power_action_needs_confirmation_then_executes(executor):
    staged = executor.power_action("shutdown")
    assert staged.needs_confirmation is True
    assert staged.token is not None

    with patch("core.system_executor.subprocess.Popen") as popen:
        result = executor.confirm(staged.token)
    assert result.ok is True
    popen.assert_called_once_with(["shutdown", "/s", "/t", "0"])


def test_power_action_unknown_mode(executor):
    result = executor.power_action("hibernate")
    assert result.ok is False
    assert result.needs_confirmation is False
