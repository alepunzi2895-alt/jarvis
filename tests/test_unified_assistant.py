import asyncio
from datetime import date, datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core import projects, work_context, databricks_catalog, claude_bridge, project_status
from core.live_server import Engine


@pytest.fixture
def catalog_root(tmp_path, monkeypatch):
    config = tmp_path / "catalog.json"
    config.write_text(json.dumps({"roots": [str(tmp_path)]}))
    notes = tmp_path / "notes"
    notes.mkdir()
    monkeypatch.setattr(projects, "CONFIG", config)
    monkeypatch.setattr(projects, "NOTES", notes)
    for key in list(os.environ):
        if key.startswith("WS_"):
            monkeypatch.delenv(key)
    return tmp_path


def repo(root, name):
    folder = root / name
    folder.mkdir()
    (folder / ".git").mkdir()
    return folder


def test_new_projects_discovered_without_restart(catalog_root):
    assert projects.find("new-project") is None
    folder = repo(catalog_root, "New_Project")
    assert projects.find("new-project").path == str(folder.resolve())
    assert projects.detect("controlla New Project") == "new-project"
    assert projects.Workspaces()["new-project"] == str(folder.resolve())


def test_aliases_followups_and_multiple_projects(catalog_root):
    repo(catalog_root, "auraibiza")
    repo(catalog_root, "tradeflow-ai")
    (projects.NOTES / "vinitalimport.md").write_text("# Vinitalimport")
    assert projects.detect("indovino il numero") == "jarvis"
    assert projects.detect("e il deploy?", "aura") == "aura"
    assert projects.detect("Jarvis, controlla Aura") == "aura"
    assert projects.detect("confronta Aura e TradeFlow", "aura") == "jarvis"
    assert projects.detect("come vanno tutti i progetti", "aura") == "jarvis"
    assert len([p for p in projects.catalog() if p.key == "aura"]) == 1


def test_read_project_files_blocks_escape_and_secrets(catalog_root):
    folder = repo(catalog_root, "new")
    (folder / "README.md").write_text("context")
    (folder / ".env").write_text("secret")
    assert work_context.read_project_file("new", "README.md")["text"] == "context"
    assert ".env" not in work_context.read_project_file("new")["entries"]
    for path in ("../catalog.json", ".env", ".git/config"):
        with pytest.raises(ValueError):
            work_context.read_project_file("new", path)


def test_discovered_git_status_is_read_only(catalog_root, monkeypatch):
    folder = repo(catalog_root, "new")
    read = Mock(side_effect=[SimpleNamespace(returncode=0, stdout="## feature\n M a.py", stderr=""),
                            SimpleNamespace(returncode=0, stdout="abc title (1 day ago)", stderr="")])
    monkeypatch.setattr(projects, "git_read", read)
    executor = Mock()
    status = project_status.check_one_by_key("new", executor)
    assert status.branch == "feature" and status.dirty_files == 1
    executor.run.assert_not_called()
    executor.git.assert_not_called()
    assert read.call_args_list[0].args == (str(folder.resolve()), "status", "--short", "--branch")


def test_calendar_overlap_midnight_and_empty():
    def event(start, end):
        return SimpleNamespace(start=datetime.fromisoformat(start), end=datetime.fromisoformat(end))
    events = [event("2026-10-12T23:30", "2026-10-13T00:30"),
              event("2026-10-13T09:00", "2026-10-13T10:00"),
              event("2026-10-13T09:30", "2026-10-13T10:30")]
    assert work_context.occupied_minutes(events, date(2026, 10, 13)) == 120
    assert work_context.occupied_minutes([], date(2026, 10, 13)) == 0


def test_focus_persistence_and_completion(monkeypatch, tmp_path):
    monkeypatch.setattr(work_context, "FOCUS_FILE", tmp_path / "focus.json")
    added = work_context.focus("add", title="Chiudere il report", due="2026-10-14")
    assert work_context.focus()[0]["status"] == "open"
    done = work_context.focus("complete", item_id=added["id"])
    assert done["completed_at"]
    assert work_context.focus("complete", item_id=added["id"])["completed_at"] == done["completed_at"]
    with pytest.raises(ValueError):
        work_context.focus("complete", item_id="missing")


def test_focus_concurrent_writes_are_not_lost(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(work_context, "FOCUS_FILE", tmp_path / "focus.sqlite3")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: work_context.focus("add", title=f"Task {i}"), range(12)))
    assert len(work_context.focus()) == 12


def test_overview_calendar_includes_events_already_started(monkeypatch):
    from core import outlook
    call = Mock(return_value=[])
    monkeypatch.setattr(outlook, "_run_in_fresh_thread", call)
    outlook.get_events_for_day_sync(date(2026, 10, 13), include_ongoing=True)
    assert call.call_args.args[1:] == (datetime(2026, 10, 13), datetime(2026, 10, 14), True)


def test_unavailable_outlook_is_not_zero(catalog_root, monkeypatch, tmp_path):
    monkeypatch.setattr(work_context, "FOCUS_FILE", tmp_path / "focus.json")
    monkeypatch.setattr(project_status, "check_all", lambda _: [])
    monkeypatch.setattr("core.outlook.get_events_for_day_sync", Mock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr("core.outlook.count_unread_emails_sync", Mock(side_effect=RuntimeError("offline")))
    result = work_context.overview("2026-10-13")
    assert result["calendar"][0]["occupied_minutes"] is None
    assert result["unread_emails"] is None
    assert "error" in result["calendar"][0]


def test_run_statistics_have_honest_denominator():
    rows = [{"state": {"result_state": x}} for x in ["SUCCESS", "FAILED", "CANCELED", None, "NEW_STATE"]]
    rows[0].update(start_time=1000, end_time=11000)
    result = databricks_catalog.run_metrics(rows)
    assert result["terminal_known"] == 3
    assert result["failure_rate_percent"] == 33.3
    assert result["active_or_unknown"] == 2
    assert result["mean_elapsed_seconds"] == 10
    assert databricks_catalog.run_metrics([])["failure_rate_percent"] is None


def test_databricks_only_get_qas_and_pagination(monkeypatch):
    monkeypatch.setattr(databricks_catalog.db, "_env_config", lambda env: {"host": "https://qas.test"} if env == "qas" else pytest.fail())
    monkeypatch.setattr(databricks_catalog.db, "_get_token", lambda env: "fake")
    response = Mock()
    response.json.return_value = {"runs": [], "next_page_token": "next"}
    get = Mock(return_value=response)
    monkeypatch.setattr(databricks_catalog.requests, "get", get)
    data = databricks_catalog.inspect("runs", page_token="previous")
    assert data["partial"] and data["next_page_token"] == "next"
    assert get.call_args.kwargs["params"]["limit"] == 25
    assert get.call_args.kwargs["params"]["page_token"] == "previous"
    assert get.call_args.args[0] == "https://qas.test/api/2.2/jobs/runs/list"
    with pytest.raises(ValueError):
        databricks_catalog.inspect("delete")


def test_databricks_get_retries_ssl_errors_from_proxy(monkeypatch):
    monkeypatch.setattr(databricks_catalog.time, "sleep", lambda _: None)
    response = Mock()
    response.json.return_value = {"runs": []}
    ssl_error = databricks_catalog.requests.exceptions.SSLError("EOF")
    get = Mock(side_effect=[ssl_error, ssl_error, response])
    monkeypatch.setattr(databricks_catalog.requests, "get", get)
    assert databricks_catalog._get("https://qas.test", {}, "/api/2.2/jobs/runs/list") == {"runs": []}
    assert get.call_count == 3
    get = Mock(side_effect=ssl_error)
    monkeypatch.setattr(databricks_catalog.requests, "get", get)
    with pytest.raises(databricks_catalog.requests.exceptions.SSLError):
        databricks_catalog._get("https://qas.test", {}, "/api/2.2/jobs/runs/list")
    assert get.call_count == 3


def test_discovery_does_not_authorize_cli_writes(catalog_root, monkeypatch):
    folder = repo(catalog_root, "New_Project")
    monkeypatch.setattr(claude_bridge._system_executor, "_in_whitelist", lambda _: False)
    launch = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    result = asyncio.run(claude_bridge._run_claude_cli("modifica", "new-project", str(folder), None, "text"))
    assert "sola lettura" in result[0]
    launch.assert_not_called()


def test_generic_project_voice_summary_avoids_model_roundtrip(monkeypatch):
    states = [project_status.ProjectStatus("aura", "Aura", "/repo", True, branch="dev", dirty_files=3)]
    monkeypatch.setattr(project_status, "cached_check_all", lambda _: states)
    model = AsyncMock()
    monkeypatch.setattr(claude_bridge, "_run_claude_api", model)
    speak = AsyncMock()
    history = {}
    result = asyncio.run(Engine().respond("come vanno i progetti?", None, history, speak))
    model.assert_not_called()
    assert result["cost_usd"] == 0
    assert "3 file modificati" in result["result"]
    assert history["_conversation"][-1]["content"] == result["result"]
    assert speak.call_count == 1


def test_live_conversation_shared_across_projects_and_model_routing(catalog_root, monkeypatch):
    repo(catalog_root, "auraibiza")
    repo(catalog_root, "EYRA")
    calls = []
    async def fake_api(prompt, ws, cwd, image, channel, **kwargs):
        calls.append((ws, kwargs["history_key"], kwargs["model"]))
        return "risposta", None, 0
    monkeypatch.setattr(claude_bridge, "_run_claude_api", fake_api)
    monkeypatch.setattr(claude_bridge, "TEXT_ENGINE", "api")
    monkeypatch.setattr("core.intents.parse_intent", lambda _: None)
    async def run():
        engine, history = Engine(), {}
        for prompt in ("Analizza Aura", "e il deploy?", "come va EYRA"):
            await engine.respond(prompt, None, history, AsyncMock())
    asyncio.run(run())
    assert [c[0] for c in calls] == ["aura", "aura", "eyra"]
    assert {c[1] for c in calls} == {"_conversation"}
    assert calls[0][2] == calls[1][2] == claude_bridge.API_MODEL
    assert calls[2][2] == claude_bridge.API_MODEL_ALIASES.get(claude_bridge.VOICE_MODEL, claude_bridge.VOICE_MODEL)


def _run(run_id, job_id, name, state, start, end, message=""):
    return {"run_id": run_id, "job_id": job_id, "run_name": name, "start_time": start, "end_time": end,
            "state": {"result_state": state, "state_message": message}, "run_page_url": f"https://prd/run/{run_id}"}


def test_prd_limited_to_job_and_dashboard_metadata(monkeypatch):
    monkeypatch.setattr(databricks_catalog.db, "_env_config", lambda env: pytest.fail("nessuna chiamata"))
    for kind in ("notebook", "workspace"):
        with pytest.raises(ValueError):
            databricks_catalog.inspect(kind, path="/Repos", env="prd")
    with pytest.raises(ValueError):
        databricks_catalog.inspect("jobs", env="dev")


def test_runs_summary_reads_all_pages_and_aggregates_per_job(monkeypatch):
    pages = [
        {"runs": [_run(1, 10, "Gold", "FAILED", 1000, 61000, "boom"), _run(2, 10, "Gold", "SUCCESS", 2000, 12000)],
         "next_page_token": "p2"},
        {"runs": [_run(3, 20, "Silver", "SUCCESS", 3000, 4000), _run(4, 10, "Gold", "FAILED", 5000, 6000, "ultimo")]},
    ]
    calls = []
    monkeypatch.setattr(databricks_catalog, "_client", lambda env: (f"https://{env}", {}))
    monkeypatch.setattr(databricks_catalog, "_get", lambda host, headers, endpoint, params: calls.append((host, params)) or pages[len(calls) - 1])
    result = databricks_catalog.runs_summary("prd", 7)
    assert result["source"] == "Databricks PRD" and result["complete"] and result["pages_read"] == 2
    assert calls[1][1]["page_token"] == "p2" and calls[0][0] == "https://prd"
    gold, silver = result["jobs"]
    assert (gold["name"], gold["runs"], gold["failed"], gold["max_elapsed_seconds"]) == ("Gold", 3, 2, 60.0)
    assert gold["last_failure"]["message"] == "ultimo"
    assert silver["failed"] == 0 and silver["last_failure"] is None
    assert result["overall"]["sample_runs"] == 4 and result["overall"]["failed"] == 2


def test_runs_summary_declares_partial_coverage_at_page_cap(monkeypatch):
    monkeypatch.setattr(databricks_catalog, "_MAX_RUN_PAGES", 2)
    monkeypatch.setattr(databricks_catalog, "_client", lambda env: ("https://prd", {}))
    monkeypatch.setattr(databricks_catalog, "_get", lambda *a: {"runs": [_run(1, 1, "J", "SUCCESS", 1, 2)], "next_page_token": "more"})
    result = databricks_catalog.runs_summary("prd", 7)
    assert not result["complete"] and result["coverage"].startswith("Parziale")


def test_compare_dashboards_matches_names_and_flags_publication(monkeypatch):
    data = {
        "qas": [dict(name="[QAS] Sales", published=True, published_at="2026-10-02T10:00:00Z", draft_updated="2026-10-02T09:00:00Z"),
                dict(name="Only test", published=True, published_at="2026-09-01T00:00:00Z", draft_updated=None),
                dict(name="Fleet", published=True, published_at="2026-09-01T00:00:00Z", draft_updated=None)],
        "prd": [dict(name="Sales PRD", published=True, published_at="2026-09-20T10:00:00Z", draft_updated="2026-09-25T00:00:00Z"),
                dict(name="Fleet", published=False, published_at=None, draft_updated="2026-09-01T00:00:00Z"),
                dict(name="Prod only", published=True, published_at="2026-08-01T00:00:00Z", draft_updated="2026-07-01T00:00:00Z")],
    }
    monkeypatch.setattr(databricks_catalog, "_dashboards_with_publication", lambda env: (data[env], False))
    result = databricks_catalog.compare_dashboards()
    status = {row["name"]: row["status"] for row in result["dashboards"]}
    assert status == {"Sales PRD": "qas_pubblicata_dopo_prd", "Fleet": "prd_non_pubblicata",
                      "Only test": "solo_qas", "Prod only": "solo_prd"}
    assert next(r for r in result["dashboards"] if r["name"] == "Sales PRD")["prd_bozza_piu_recente"]
    assert result["qas_count"] == 3 and result["prd_count"] == 3


def test_compare_dashboards_keeps_other_env_when_one_fails(monkeypatch):
    def load(env):
        if env == "prd":
            raise RuntimeError("403")
        return [dict(name="A", published=True, published_at="x", draft_updated=None)], False
    monkeypatch.setattr(databricks_catalog, "_dashboards_with_publication", load)
    result = databricks_catalog.compare_dashboards()
    assert "403" in result["prd_error"] and result["counts"] == {"solo_qas": 1}


def test_dashboard_publication_handles_404_and_rate_limit(monkeypatch):
    def response(status, body=None, headers=None):
        r = Mock(status_code=status, headers=headers or {})
        r.json.return_value = body or {}
        if status >= 400:
            r.raise_for_status.side_effect = databricks_catalog.requests.HTTPError(response=r)
        return r
    replies = iter([
        response(429, headers={"Retry-After": "0"}),
        response(200, {"dashboards": [{"dashboard_id": "a", "display_name": "A"}, {"dashboard_id": "b", "display_name": "B"}]}),
        response(200, {"path": "/a", "update_time": "2026-10-01"}), response(200, {"revision_create_time": "2026-10-02"}),
        response(200, {"path": "/b", "update_time": "2026-10-01"}), response(404),
    ])
    session = Mock()
    session.headers = {}
    session.get.side_effect = lambda *a, **k: next(replies)
    monkeypatch.setattr(databricks_catalog.requests, "Session", lambda: session)
    monkeypatch.setattr(databricks_catalog, "_client", lambda env: ("https://prd", {"Authorization": "Bearer x"}))
    monkeypatch.setattr(databricks_catalog.time, "sleep", lambda s: None)
    items, partial = databricks_catalog._dashboards_with_publication("prd")
    assert not partial
    assert [(i["name"], i["published"], i["published_at"]) for i in items] == [("A", True, "2026-10-02"), ("B", False, None)]
