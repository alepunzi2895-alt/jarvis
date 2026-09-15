import time
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
    # Bare MagicMock(): gli altri progetti (trading/whitesoul) hanno path
    # reali in .env e proseguono oltre il check "non configurato" - servono
    # risposte git realistiche (stringhe vere) anche per loro, non contano
    # per questo test ma non devono far esplodere il parsing.
    statuses = project_status.check_all(_make_executor(_ok("## main")))
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.configured is False
    assert aura.path is None


def test_not_configured_when_path_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("WS_AURA", str(tmp_path / "non-esiste"))
    statuses = project_status.check_all(_make_executor(_ok("## main")))
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


def test_clean_recent_repo_captures_timestamp_and_full_health(monkeypatch, tmp_path):
    repo = tmp_path / "auraibiza"
    repo.mkdir()
    monkeypatch.setenv("WS_AURA", str(repo))
    now_ts = int(time.time())
    executor = _make_executor(_ok("## main...origin/main"), _ok(f"abc123 fix qualcosa (2 ore fa)|{now_ts}"))
    statuses = project_status.check_all(executor)
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.last_commit == "abc123 fix qualcosa (2 ore fa)"  # testo mostrato invariato
    assert aura.last_commit_ts == now_ts
    assert aura.health_percent == 100


def test_health_percent_none_when_not_configured(monkeypatch):
    monkeypatch.delenv("WS_AURA", raising=False)
    statuses = project_status.check_all(_make_executor(_ok("## main")))
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.health_percent is None


def test_health_percent_penalizes_dirty_files_and_known_issue_flag(monkeypatch, tmp_path):
    repo = tmp_path / "tradeflow-ai"
    repo.mkdir()
    monkeypatch.setenv("WS_AURA", str(repo))
    executor = _make_executor(_ok("## main...origin/main\n M a.py\n M b.py"))
    monkeypatch.setattr(
        project_status, "_read_notes_excerpt", lambda notes_file: "## Stato\n🔴 Bot fermo." if notes_file == "aura-ibiza.md" else None
    )
    statuses = project_status.check_all(executor)
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.dirty_files == 2
    assert aura.health_percent == 40  # 100 - 50 (flag noto) - 10 (2 file sporchi)


def test_health_percent_penalizes_stale_commits(monkeypatch, tmp_path):
    repo = tmp_path / "auraibiza"
    repo.mkdir()
    monkeypatch.setenv("WS_AURA", str(repo))
    old_ts = int(time.time()) - 40 * 86400  # 40 giorni fa
    executor = _make_executor(_ok("## main...origin/main"), _ok(f"abc123 fix (40 giorni fa)|{old_ts}"))
    statuses = project_status.check_all(executor)
    aura = next(s for s in statuses if s.key == "aura")
    assert aura.health_percent == 70  # 100 - 30 (oltre 30 giorni senza commit)


def test_to_json_ready_serializes_all_fields():
    statuses = [project_status.ProjectStatus(key="aura", label="Aura Ibiza", path=None, configured=False)]
    data = project_status.to_json_ready(statuses)
    assert data == [
        {
            "key": "aura", "label": "Aura Ibiza", "path": None, "configured": False,
            "branch": None, "dirty_files": 0, "last_commit": None, "last_commit_ts": None,
            "notes": None, "error": None, "health_percent": None,
        }
    ]


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
