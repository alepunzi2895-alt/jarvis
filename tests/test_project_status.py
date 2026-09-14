from unittest.mock import MagicMock

from core import project_status


def _ok(stdout="", stderr=""):
    return MagicMock(ok=True, stdout=stdout, stderr=stderr)


def _fail(stderr="errore"):
    return MagicMock(ok=False, stdout="", stderr=stderr)


def _make_executor(status_result, log_result=None):
    executor = MagicMock()

    def fake_git(action, repo):
        return status_result if action.startswith("status") else (log_result or _ok())

    executor.git.side_effect = fake_git
    return executor


def test_not_configured_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("WS_AURA", raising=False)
    statuses = project_status.check_all(MagicMock())
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.configured is False
    assert aura.path is None


def test_not_configured_when_path_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("WS_AURA", str(tmp_path / "non-esiste"))
    statuses = project_status.check_all(MagicMock())
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.configured is False


def test_clean_repo_reports_zero_dirty(monkeypatch, tmp_path):
    repo = tmp_path / "auraibiza"
    repo.mkdir()
    monkeypatch.setenv("WS_AURA", str(repo))
    executor = _make_executor(
        _ok("## main...origin/main"), _ok("abc123 fix qualcosa (2 giorni fa)")
    )
    statuses = project_status.check_all(executor)
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.configured is True
    assert aura.branch == "main"
    assert aura.dirty_files == 0
    assert aura.last_commit == "abc123 fix qualcosa (2 giorni fa)"
    assert aura.error is None


def test_dirty_repo_counts_changed_files(monkeypatch, tmp_path):
    repo = tmp_path / "auraibiza"
    repo.mkdir()
    monkeypatch.setenv("WS_AURA", str(repo))
    executor = _make_executor(_ok("## main...origin/main\n M file1.py\n?? file2.py"))
    statuses = project_status.check_all(executor)
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.dirty_files == 2


def test_git_error_is_captured_not_raised(monkeypatch, tmp_path):
    repo = tmp_path / "auraibiza"
    repo.mkdir()
    monkeypatch.setenv("WS_AURA", str(repo))
    executor = _make_executor(_fail("not a git repository"))
    statuses = project_status.check_all(executor)
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.error is not None
    assert "not a git repository" in aura.error


def test_read_notes_excerpt_stops_at_next_heading(monkeypatch, tmp_path):
    notes_dir = tmp_path / "projects"
    notes_dir.mkdir()
    (notes_dir / "aura-ibiza.md").write_text(
        "# Aura Ibiza\n\n## Stato\nTutto ok.\n\n## Prossimi passi\nNon deve comparire.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(project_status, "_NOTES_DIR", notes_dir)
    excerpt = project_status._read_notes_excerpt("aura-ibiza.md")
    assert "Tutto ok" in excerpt
    assert "Non deve comparire" not in excerpt


def test_read_notes_excerpt_missing_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(project_status, "_NOTES_DIR", tmp_path / "does-not-exist")
    assert project_status._read_notes_excerpt("whitesoulibiza.md") is None


def test_format_report_voice_flags_known_issue():
    statuses = [
        project_status.ProjectStatus(
            key="trading",
            label="TradeFlow AI",
            path="/x",
            configured=True,
            branch="main",
            dirty_files=0,
            notes="## Stato\n🔴 Bot fermo dal 2026-07-10.",
        ),
    ]
    text = project_status.format_report(statuses, voice=True)
    assert "Signore" in text
    assert "problema noto" in text


def test_format_report_text_lists_all_projects():
    statuses = [
        project_status.ProjectStatus(key="aura", label="Aura Ibiza", path=None, configured=False),
        project_status.ProjectStatus(
            key="trading",
            label="TradeFlow AI",
            path="/x",
            configured=True,
            branch="main",
            dirty_files=1,
            last_commit="abc123 fix (1 giorno fa)",
        ),
    ]
    text = project_status.format_report(statuses, voice=False)
    assert "Aura Ibiza" in text and "non configurato" in text
    assert "TradeFlow AI" in text and "1 modifiche non committate" in text
    assert "abc123 fix (1 giorno fa)" in text
