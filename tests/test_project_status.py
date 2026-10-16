from unittest.mock import MagicMock
import pytest

from core import project_status


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch):
    # Questi test verificano il parser Git/compatibilita' WS_; la scoperta
    # dinamica ha test separati e non deve scandire il PC durante la suite.
    monkeypatch.setattr(project_status, "PROJECTS", [
        project_status.ProjectConfig("aura", "Aura Ibiza", "WS_AURA", "aura-ibiza.md"),
        project_status.ProjectConfig("trading", "TradeFlow AI", "WS_TRADING", "tradeflow-ai.md"),
    ])


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
    assert "Signore" not in text
    assert "problema noto" in text


def test_to_json_ready_serializes_all_fields():
    statuses = [project_status.ProjectStatus(key="aura", label="Aura Ibiza", path=None, configured=False)]
    data = project_status.to_json_ready(statuses)
    assert data == [
        {
            "key": "aura", "label": "Aura Ibiza", "path": None, "configured": False,
            "branch": None, "dirty_files": 0, "last_commit": None,
            "notes": None, "error": None,
        }
    ]


def test_check_one_by_key_returns_single_project(monkeypatch, tmp_path):
    repo = tmp_path / "auraibiza"
    repo.mkdir()
    monkeypatch.setenv("WS_AURA", str(repo))
    executor = _make_executor(_ok("## main...origin/main"), _ok("abc123 fix (1 ora fa)"))
    status = project_status.check_one_by_key("aura", executor)
    assert status is not None
    assert status.key == "aura"
    assert status.configured is True
    assert status.last_commit == "abc123 fix (1 ora fa)"


def test_check_one_by_key_unknown_key_returns_none():
    assert project_status.check_one_by_key("non-esiste", MagicMock()) is None


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


def test_attention_omits_healthy_projects_and_limits_spoken_items():
    statuses = [project_status.ProjectStatus(f"ok{i}", f"Healthy {i}", "/repo", True, branch="main") for i in range(12)]
    statuses += [project_status.ProjectStatus("dirty", "Working", "/repo", True, branch="dev", dirty_files=3),
                 project_status.ProjectStatus("error", "Blocked", "/repo", True, error="git failed"),
                 project_status.ProjectStatus("extra", "Another", "/repo", True, branch="dev", dirty_files=2)]
    report = project_status.attention_report(statuses)
    assert len(report["highlights"]) == 2 and report["additional_items"] == 1
    assert report["highlights"][0]["project"] == "error"
    spoken = project_status.format_report(statuses, voice=True)
    assert "Healthy" not in spoken and "Another" not in spoken
    assert "da rivedere" in spoken and "non verificabile" in spoken


def test_project_overview_does_not_intercept_explicit_lists_or_analysis():
    assert project_status.is_overview_request("Jarvis, come vanno i miei progetti?")
    assert not project_status.is_overview_request("elencami tutti i progetti")
    assert not project_status.is_overview_request("analizza tutti i progetti e confrontali")


def test_snapshot_reuses_scan_and_invalidates_on_new_project(monkeypatch):
    check = MagicMock(return_value=[])
    monkeypatch.setattr(project_status, "check_all", check)
    executor = MagicMock()
    project_status.cached_check_all(executor)
    project_status.cached_check_all(executor)
    assert check.call_count == 1
    project_status.PROJECTS.append(project_status.ProjectConfig("new", "New", "WS_NEW", "new.md"))
    project_status.cached_check_all(executor)
    assert check.call_count == 2


def test_snapshot_expires_after_30_seconds(monkeypatch):
    clock = {"now": 100}
    monkeypatch.setattr(project_status.time, "monotonic", lambda: clock["now"])
    check = MagicMock(return_value=[])
    monkeypatch.setattr(project_status, "check_all", check)
    executor = MagicMock()
    project_status.cached_check_all(executor)
    clock["now"] += 29
    project_status.cached_check_all(executor)
    assert check.call_count == 1
    clock["now"] += 1
    project_status.cached_check_all(executor)
    assert check.call_count == 2


def test_git_scans_run_concurrently_and_keep_catalog_order(monkeypatch):
    import threading
    barrier = threading.Barrier(4)
    configs = [project_status.ProjectConfig(str(i), str(i), "WS_TEST", "") for i in range(4)]
    monkeypatch.setattr(project_status, "PROJECTS", configs)
    def check(cfg, executor):
        barrier.wait(timeout=2)
        return cfg
    monkeypatch.setattr(project_status, "_check_one", check)
    assert project_status.check_all(MagicMock()) == configs
