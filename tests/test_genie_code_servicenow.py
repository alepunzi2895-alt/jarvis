import asyncio
from datetime import datetime
import threading

import pytest

from core import genie_code, servicenow


@pytest.fixture
def browser_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join()
    loop.close()


def test_genie_code_collects_and_saves_chats(monkeypatch, tmp_path, browser_loop):
    from core import browser, databricks
    monkeypatch.setattr(genie_code, "SAVE_DIR", tmp_path)
    monkeypatch.setitem(databricks._ENVIRONMENTS["qas"], "host", "https://qas.example")
    monkeypatch.setitem(databricks._ENVIRONMENTS["prd"], "host", "https://prd.example")
    secret = "dapi" + "a1b2c3d4" * 5
    chat = dict(id="203", title="Dashboard Alert Templates", modified=1761638829000, messages=[
        dict(role="user", text="aggiorna i template degli alert, token " + secret),
        dict(role="assistant", text="Fatto commit e push su dev_ale.")])
    calls = []

    class Agent:
        async def evaluate_on(self, url, ready, script, arg=None):
            calls.append((url, arg["max"]))
            if "prd" in url:
                raise PermissionError("login")
            return [chat]

    monkeypatch.setattr(browser, "get_agent", lambda: Agent())
    rows = genie_code.collect(datetime(2026, 10, 27), browser_loop)
    assert [url for url, _ in calls] == ["https://qas.example", "https://prd.example"]
    assert rows[0]["env"] == "QAS" and rows[0]["last_answer"] == "Fatto commit e push su dev_ale."
    assert secret not in rows[0]["prompts"][0]
    assert rows[1] == dict(note="Ambienti non letti: PRD: PermissionError")
    saved = (tmp_path / rows[0]["saved_as"]).read_text(encoding="utf-8")
    assert saved.startswith("# Dashboard Alert Templates") and "## Genie Code" in saved
    assert secret not in saved


def test_genie_code_fails_when_no_environment_answers(monkeypatch, tmp_path, browser_loop):
    from core import browser, databricks
    monkeypatch.setattr(genie_code, "SAVE_DIR", tmp_path)
    monkeypatch.setitem(databricks._ENVIRONMENTS["qas"], "host", "https://qas.example")
    monkeypatch.setitem(databricks._ENVIRONMENTS["prd"], "host", "")

    class Agent:
        async def evaluate_on(self, *args, **kwargs):
            raise TimeoutError

    monkeypatch.setattr(browser, "get_agent", lambda: Agent())
    with pytest.raises(RuntimeError, match="QAS: TimeoutError"):
        genie_code.collect(datetime(2026, 10, 27), browser_loop)
    with pytest.raises(RuntimeError):
        genie_code.collect(datetime(2026, 10, 27), None)


def _task(number, state, active, opened, **extra):
    return dict(dict(number=number, state=state, state_code="", active=active, assigned_to="ALESSANDRO PUNZI",
                     ritm="RITM0" + number[-6:], opened_at=opened, closed_at="", updated_at=opened, priority="",
                     short_description="Data Room Requests", description="", work_notes=""), **extra)


def test_ticket_stats_flag_stale_wip_and_development():
    now = datetime(2026, 10, 28, 10, 0).astimezone()
    rows = [
        _task("SCTASK0636917", "Work in Progress", True, "2025-08-14 14:16:28",
              work_notes="2026-04-13 12:42:50 - GABRIELE GENOVESE (Work notes)\nGPU disponibili\n\n"
                         "2026-01-10 09:00:00 - ALESSANDRO PUNZI (Work notes)\nvecchia"),
        _task("SCTASK0700001", "Work in Progress", True, "2026-10-20 08:00:00",
              work_notes="2026-10-27 15:12:55 - GABRIELE GENOVESE (Work notes)\nin sviluppo"),
        _task("SCTASK0700002", "Pending", True, "2026-10-01 08:00:00", assigned_to=""),
        _task("SCTASK0600000", "Closed Successful", False, "2026-10-01 08:00:00", closed_at="2026-10-21 08:00:00"),
        _task("SCTASK0600001", "Closed CANCELLED", False, "2026-09-20 08:00:00", closed_at="2026-10-22 08:00:00"),
    ]
    data = servicenow.stats(rows, now, {"RITM0700001": ["pull request DevOps"]})
    assert data["open"] == 3 and data["work_in_progress"] == 2
    assert data["by_state"] == {"Work in Progress": 2, "Pending": 1}
    assert data["by_person"] == {"ALESSANDRO PUNZI": 2, "non assegnato": 1}
    assert data["wip_without_development"] == 1
    old, new, pending = data["tickets"]  # prima i WIP, i piu' vecchi in testa
    assert old["number"] == "SCTASK0636917" and old["stale"] and old["last_note"] == "2026-04-13"
    assert old["last_note_by"] == "Gabriele Genovese"
    assert new["linked_development"] == ["pull request DevOps"] and not new["stale"]
    assert pending["days_without_notes"] == 27 and not pending["stale"]
    assert data["last_30_days"] == dict(opened=3, closed=2, cancelled=1)
    assert data["median_days_to_close"] == 20
    assert sum(week["closed"] for week in data["weeks"]) == 2


def test_recap_facts_are_compact(monkeypatch):
    rows = [_task("SCTASK0700001", "Work in Progress", True, "2026-10-20 08:00:00", description="x" * 800)]
    monkeypatch.setattr(servicenow, "read_tasks", lambda loop: rows)
    monkeypatch.setattr(servicenow, "development_refs", lambda since: ({}, {}))
    facts = servicenow.recap_facts(object(), datetime(2026, 10, 28, 10, 0))
    assert facts["work_in_progress"] == 1 and "tickets" not in facts and "weeks" not in facts
    assert set(facts["open_tickets"][0]) == {"number", "state", "assigned_to", "age_days", "days_without_notes",
                                             "stale", "linked_development"}


def test_read_tasks_retries_once_after_aborted_fetch(monkeypatch, browser_loop):
    from core import browser
    calls = []

    class Agent:
        async def evaluate_on(self, url, ready, script, arg=None):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError("Page.evaluate: TypeError: Failed to fetch")
            return [{"number": "SCTASK1"}]

    monkeypatch.setattr(browser, "get_agent", lambda: Agent())
    assert servicenow.read_tasks(browser_loop) == [{"number": "SCTASK1"}]
    assert calls == [servicenow.LIST_URL] * 2


def _row(number="SCTASK1234567", state="Work in Progress", assigned="Alessandro Punzi"):
    return dict(sys_id="a" * 32, number=number, ritm="RITM7654321", state=state, state_code="2", active=True,
                assigned_to=assigned, opened_at="2026-10-01 09:00:00", closed_at="", updated_at="2026-10-20 09:00:00",
                priority="3", short_description="Template alert", description="Aggiungere il filtro per sito",
                work_notes="")


def test_stage_update_prepares_without_writing(monkeypatch):
    monkeypatch.setattr(servicenow, "read_tasks", lambda loop: [_row()])
    writes = []
    monkeypatch.setattr(servicenow, "confirm_update", lambda token, loop=None: writes.append(token))
    staged = servicenow.stage_update(object(), "sctask1234567", state="Pending")
    assert staged["confirm"] == f"/confirm {staged['token']}"
    assert "'Work in Progress' -> 'Pending'" in staged["changes"]
    assert writes == [] and servicenow.has_pending(staged["token"])
    assert servicenow.deny_update(staged["token"]) and not servicenow.has_pending(staged["token"])


def test_stage_update_rejects_bad_input(monkeypatch):
    monkeypatch.setattr(servicenow, "read_tasks", lambda loop: [_row()])
    with pytest.raises(servicenow.ServiceNowError):
        servicenow.stage_update(object(), "INC123")
    with pytest.raises(servicenow.ServiceNowError):
        servicenow.stage_update(object(), "SCTASK1234567")
    with pytest.raises(servicenow.ServiceNowError):
        servicenow.stage_update(object(), "SCTASK9999999", state="Pending")


def test_confirm_update_patches_once_and_expired_token_fails(monkeypatch, browser_loop):
    from core import browser
    monkeypatch.setattr(servicenow, "read_tasks", lambda loop: [_row()])
    sent = []

    class Agent:
        async def evaluate_on(self, url, ready, script, arg=None):
            sent.append(arg)
            return dict(state="Pending", assigned_to="Dario Campolo")

    monkeypatch.setattr(browser, "get_agent", lambda: Agent())
    staged = servicenow.stage_update(browser_loop, "SCTASK1234567", state="Pending", assigned_to="Dario Campolo")
    message = servicenow.confirm_update(staged["token"], browser_loop)
    assert sent == [{"sysId": "a" * 32, "body": {"state": "Pending", "assigned_to": "Dario Campolo"}}]
    assert message == "SCTASK1234567 aggiornato: stato Pending, assegnato a Dario Campolo."
    with pytest.raises(servicenow.ServiceNowError):
        servicenow.confirm_update(staged["token"], browser_loop)
    expired = servicenow.stage_update(browser_loop, "SCTASK1234567", state="Pending")
    servicenow._pending_updates[expired["token"]]["at"] -= servicenow.PENDING_TTL + 1
    with pytest.raises(servicenow.ServiceNowError):
        servicenow.confirm_update(expired["token"], browser_loop)


def test_draft_genie_new_or_existing_dashboard():
    ticket = dict(number="SCTASK1234567", short_description="Template alert", description="Filtro per sito")
    new = genie_code.draft_request(ticket, "new")
    assert "Crea da zero" in new and "SCTASK1234567" in new
    existing = genie_code.draft_request(ticket, "existing", "Alert Dashboard QAS")
    assert "Estendi la dashboard esistente 'Alert Dashboard QAS'" in existing
    with pytest.raises(ValueError):
        genie_code.draft_request(ticket, "existing")
    with pytest.raises(ValueError):
        genie_code.draft_request(ticket, "boh")
