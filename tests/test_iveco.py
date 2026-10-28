import asyncio
from datetime import datetime, timedelta
import json
import threading

import pytest

from core import iveco


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 10, 19, 9, 30), datetime(2026, 10, 16)),  # lunedi' -> venerdi'
    (datetime(2026, 10, 16, 9, 30), datetime(2026, 10, 15)),  # venerdi' -> giovedi'
    (datetime(2026, 10, 18, 12, 0), datetime(2026, 10, 16)),  # domenica -> venerdi'
])
def test_window_starts_on_previous_working_day(now, expected):
    assert iveco.window_start(now) == expected


def test_next_recap_skips_weekend_and_past_times(monkeypatch):
    monkeypatch.setattr(iveco, "RECAP_TIME", "09:30")
    assert iveco.next_recap_at(datetime(2026, 10, 16, 8, 0)) == datetime(2026, 10, 16, 9, 30)
    assert iveco.next_recap_at(datetime(2026, 10, 16, 9, 30)) == datetime(2026, 10, 19, 9, 30)
    assert iveco.next_recap_at(datetime(2026, 10, 17, 7, 0)) == datetime(2026, 10, 19, 9, 30)


def test_gather_survives_every_source_failing(monkeypatch):
    def broken(*args):
        raise RuntimeError("giu'")
    for name in ("_job_runs", "_workspace_changes", "_dashboard_changes", "_apps", "_deploys", "_ivgagent", "_mail", "_meetings"):
        monkeypatch.setattr(iveco, name, broken)
    data = iveco.gather(datetime(2026, 10, 16, 9, 30))
    assert data["since"] == "2026-10-15 00:00"
    assert data["facts"] == {}
    assert data["sources"]["mail"] == "non disponibile (RuntimeError)"
    assert data["sources"]["teams"] == "non disponibile (RuntimeError)"  # nessun loop browser


def test_build_recap_saves_summary_and_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(iveco, "RECAP_FILE", tmp_path / ".iveco-recap.json")
    monkeypatch.setattr(iveco, "gather", lambda now=None, loop=None: dict(now="2026-10-16 09:30", since="2026-10-15 00:00",
                                                               facts={"mail": []}, sources={"mail": "ok"}))
    monkeypatch.setattr(iveco, "summarize", lambda data: "Fatto: nulla di rilevante")
    record = iveco.build_recap()
    assert record["text"] == "Fatto: nulla di rilevante"
    assert iveco.latest() == record
    assert json.loads((tmp_path / ".iveco-recap.json").read_text(encoding="utf-8"))["since"] == "2026-10-15 00:00"


def test_deploys_are_split_per_person(monkeypatch):
    from core import azure_devops
    monkeypatch.setattr(iveco, "PEOPLE", "punzi=Alessandro,gabr=Gabry")
    monkeypatch.setattr(azure_devops, "snapshot", lambda: dict(
        deployments=[dict(name="Data / R-1", environment="PRD", status="succeeded", at="2026-10-15T16:00:00Z", by="ROSSI Gabriele"),
                     dict(name="Old", environment="QAS", status="succeeded", at="2026-10-01T16:00:00Z", by="PUNZI Alessandro")],
        stages=[dict(name="Deploy to QAS", status="succeeded", at="2026-10-15T15:00:00Z", by="PUNZI Alessandro")],
        builds=[dict(name="Solo l'ultima per pipeline", at="2026-10-15T14:00:00Z", by="PUNZI Alessandro")],
        pull_requests=[dict(title="Fleet KPI", at="2026-10-15T10:00:00Z", by="PUNZI Alessandro")]))
    # Tutte le build della finestra, anche i push su dev_ale prima del merge (2026-10-27).
    monkeypatch.setattr(azure_devops, "builds_since", lambda since: [
        dict(name="Data", branch="refs/heads/dev_ale", message="Alerts v7: template A/B", at="2026-10-15T13:00:00Z",
             by="PUNZI Alessandro"),
        dict(name="Data", at="2026-10-15T14:00:00Z", by="Project Collection Build Service")])
    people = iveco._deploys(datetime(2026, 10, 15))
    assert set(people) == {"Alessandro", "Gabry", "Project Collection Build Service"}
    assert [b["message"] for b in people["Alessandro"]["builds"]] == ["Alerts v7: template A/B"]
    assert [d["environment"] for d in people["Gabry"]["deployments"]] == ["PRD"]
    assert "deployments" not in people["Alessandro"]  # quello vecchio e' fuori finestra
    assert people["Alessandro"]["pull_requests"][0]["title"] == "Fleet KPI"
    assert iveco._owner(None) == "sconosciuto"


def test_iso_after_handles_utc_and_bad_values():
    since = datetime(2026, 10, 15)
    assert iveco._iso_after("2026-10-16T08:00:00Z", since)
    assert not iveco._iso_after("2026-10-01T08:00:00Z", since)
    assert not iveco._iso_after(None, since)
    assert not iveco._iso_after("ieri", since)


def test_teams_reads_chat_list_on_browser_loop(monkeypatch):
    from core import browser
    rossi = dict(id="19:a", kind="OneGQL_OneOnOneChatConversation", title="ROSSI Mario",
                 preview="puoi guardare il job?", at="2026-10-16T07:10:00Z", unread=True)

    class Agent:
        async def read_teams_chats(self, url):
            assert url == iveco.TEAMS_URL
            return [
                rossi,
                dict(rossi),  # stessa chat anche tra i Preferiti
                dict(id="48:notes", kind="OneGQL_SelfChatConversation", title="PUNZI (You)",
                     preview="VPS password", at="2026-10-16T08:00:00Z", unread=False),
                dict(id="19:b", kind="OneGQL_GroupChatConversation", title="Vecchia",
                     preview="x", at="2026-10-01T08:00:00Z", unread=False),
            ]

    monkeypatch.setattr(browser, "get_agent", lambda: Agent())
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        rows = iveco._teams(datetime(2026, 10, 15), loop)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()
    assert [row["chat"] for row in rows] == ["ROSSI Mario"]
    assert rows[0]["type"] == "1:1" and rows[0]["unread"]
    assert rows[0]["last_message"] == "puoi guardare il job?"


def test_recap_loop_sends_due_recap_with_browser_loop(monkeypatch):
    clock = iter([datetime(2026, 10, 16, 9, 0), datetime(2026, 10, 16, 9, 31)])
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(clock)
    sent, loops = [], []
    def build(now=None, loop=None):
        loops.append(loop)
        return {"text": "Fatto: deploy"}
    async def no_wait(seconds):
        if len(sent):
            raise asyncio.CancelledError
    monkeypatch.setattr(iveco, "datetime", Clock)
    monkeypatch.setattr(iveco, "RECAP_TIME", "09:30")
    monkeypatch.setattr(iveco, "build_recap", build)
    monkeypatch.setattr(iveco.asyncio, "sleep", no_wait)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(iveco.recap_loop(sent.append))
    assert sent == ["Recap per il daily delle 10:00\n\nFatto: deploy"]
    assert loops[0] is not None  # Teams si legge sul loop di LiveBridge


def test_ivgagent_reads_commits_pending_files_and_tools(monkeypatch, tmp_path):
    import subprocess
    from core import ivg_dbx
    repo = tmp_path / "repo" / "data-room"
    repo.mkdir(parents=True)
    run = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "dev_ale")
    run("config", "user.name", "alepunzi2895-alt")
    run("config", "user.email", "a@example.com")
    (repo / "Asset.ipynb").write_text("{}")
    run("add", ".")
    run("commit", "-qm", "fix(silver): IVGct parity fields\n\nWhy it matters.\n\nCo-Authored-By: Claude <x@y>")
    (repo / "draft.sql").write_text("select 1")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "lvdash.py").write_text("")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "profile.bin").write_text("")
    monkeypatch.setattr(ivg_dbx, "IVG_ROOT", tmp_path)
    data = iveco._ivgagent(datetime(2000, 1, 1))
    [entry] = data["repos"]
    assert entry["repo"] == "data-room" and entry["branch"] == "dev_ale"
    [commit] = entry["commits"]
    assert commit["by"] == "Alessandro" and commit["branches"] == ["dev_ale"]
    assert commit["message"] == "fix(silver): IVGct parity fields\n\nWhy it matters."
    assert commit["files"] == ["Asset.ipynb"]
    assert entry["uncommitted"] == ["draft.sql"]
    assert data["tools_changed"] == ["tools/lvdash.py"]
    assert iveco._ivgagent(datetime.now() + timedelta(days=1)) == {"repos": [{"repo": "data-room", "branch": "dev_ale",
                                                             "commits": [], "uncommitted": ["draft.sql"]}],
                                                  "tools_changed": [], "sessions": []}


def test_ivg_sessions_read_prompts_edits_and_state(tmp_path):
    from core import agent_sessions
    root = tmp_path / "IVGAgent"
    folder = agent_sessions.CLAUDE_DIR / iveco.re.sub(r"[:\\/]", "-", str(root))
    folder.mkdir(parents=True)
    rows = [
        {"type": "ai-title", "aiTitle": "App Qlik su Databricks QAS"},
        {"type": "user", "timestamp": "2026-10-21T09:00:00Z", "message": {"content": "vecchia richiesta"}},
        {"type": "user", "timestamp": "2026-10-22T09:05:00Z",
         "message": {"content": "ricrea la app Qlik, token " + "a" * 40}},
        {"type": "user", "timestamp": "2026-10-22T09:06:00Z", "message": {"content": "<task-notification>x"}},
        {"type": "user", "timestamp": "2026-10-22T09:07:00Z", "isMeta": True, "message": {"content": "meta"}},
        {"type": "assistant", "timestamp": "2026-10-22T10:00:00Z", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "C:/IVGAgent/tools/lvdash.py"}},
            {"type": "text", "text": "Dashboard pubblicata in QAS."}], "stop_reason": "end_turn"}},
        {"type": "assistant", "timestamp": "2026-10-22T11:00:00Z", "isApiErrorMessage": True,
         "message": {"content": [{"type": "text", "text": "You've hit your session limit"}], "stop_reason": "stop_sequence"}},
    ]
    (folder / "s1.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\nnot json\n", encoding="utf-8")
    [session] = iveco._ivg_sessions(root, datetime(2026, 10, 22))
    assert session["title"] == "App Qlik su Databricks QAS"
    assert [p["text"] for p in session["prompts"]] == ["ricrea la app Qlik, token [oscurato]"]
    assert session["files_edited"] == ["lvdash.py"]
    assert session["last_answer"] == "Dashboard pubblicata in QAS."
    assert session["state"] == "in attesa di Alessandro"
