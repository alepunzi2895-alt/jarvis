"""Agenda e obiettivi espliciti: misure verificabili, non punteggi di produttivita'."""
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sqlite3
import uuid

from core import projects, project_status

FOCUS_FILE = projects.ROOT / ".focus.sqlite3"


def focus(action="list", title="", item_id="", project="", due=""):
    if action == "list" and not FOCUS_FILE.exists():
        return []
    if action == "add":
        if not title.strip() or len(title) > 500:
            raise ValueError("Titolo obbligatorio, massimo 500 caratteri")
        if due:
            date.fromisoformat(due)
        if project and not projects.find(project):
            raise ValueError("Progetto sconosciuto")
    elif action not in {"list", "complete"}:
        raise ValueError("Azione non supportata")
    connection = sqlite3.connect(FOCUS_FILE, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS focus (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, project TEXT NOT NULL,
                due TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                completed_at TEXT)""")
            if action == "list":
                return [dict(row) for row in connection.execute("SELECT * FROM focus ORDER BY created_at")]
            if action == "add":
                item_id = uuid.uuid4().hex[:12]
                connection.execute("INSERT INTO focus VALUES (?,?,?,?,?,?,NULL)",
                                   (item_id, title.strip(), project, due, "open", datetime.now().isoformat()))
            else:
                connection.execute("UPDATE focus SET status='done', completed_at=? WHERE id=? AND status='open'",
                                   (datetime.now().isoformat(), item_id))
            row = connection.execute("SELECT * FROM focus WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise ValueError("Obiettivo non trovato")
            return dict(row)
    finally:
        connection.close()


def occupied_minutes(events, day):
    """Unione intervalli: sovrapposizioni contate una volta, taglio a mezzanotte."""
    low, high = datetime.combine(day, time()), datetime.combine(day + timedelta(days=1), time())
    spans = sorted((max(e.start.replace(tzinfo=None), low), min(e.end.replace(tzinfo=None), high))
                   for e in events)
    total, end = 0, low
    for start, stop in spans:
        start = max(start, end)
        if stop > start:
            total += (stop - start).total_seconds()
            end = stop
    return round(total / 60, 1)


def overview(start="", days=1):
    from core import outlook
    from core.executor_singleton import executor
    first = date.fromisoformat(start) if start else date.today()
    days = int(days)
    if not 1 <= days <= 7:
        raise ValueError("Periodo ammesso: 1-7 giorni")
    result = dict(observed_at=datetime.now().isoformat(), start=first.isoformat(), days=days,
                  calendar=[], projects=project_status.to_json_ready(project_status.cached_check_all(executor)),
                  focus=focus(), sources={})
    for offset in range(days):
        day = first + timedelta(days=offset)
        try:
            events = outlook.get_events_for_day_sync(day, include_ongoing=True)
            result["calendar"].append(dict(date=day.isoformat(), events=[
                dict(subject=e.subject, start=e.start.isoformat(), end=e.end.isoformat()) for e in events],
                occupied_minutes=occupied_minutes(events, day)))
        except Exception as exc:
            result["calendar"].append(dict(date=day.isoformat(), error=str(exc), occupied_minutes=None))
    try:
        result["unread_emails"] = outlook.count_unread_emails_sync()
    except Exception as exc:
        result["unread_emails"] = None
        result["sources"]["outlook_mail_error"] = str(exc)
    result["sources"].update(calendar="Outlook locale, intervalli uniti; non ore lavorate",
                             projects="Git locale: stato attuale, non avanzamento percentuale",
                             focus="Obiettivi registrati esplicitamente in JARVIS; non tutti i task lavorativi")
    end = first + timedelta(days=days)
    result["focus_metrics"] = dict(
        open_items=sum(i["status"] == "open" for i in result["focus"]),
        completed_in_period=sum(bool(i.get("completed_at")) and first <= date.fromisoformat(i["completed_at"][:10]) < end
                                for i in result["focus"]),
        overdue_open_now=sum(i["status"] == "open" and bool(i.get("due")) and date.fromisoformat(i["due"]) < date.today()
                             for i in result["focus"]))
    return result


def read_project_file(project, path="."):
    p = projects.find(project)
    if not p or not p.path:
        raise ValueError("Progetto senza cartella locale")
    root = Path(p.path).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Percorso fuori dal progetto")
    relative = target.relative_to(root)
    blocked = {".git", ".venv", "node_modules", ".browser_profile", ".face_data"}
    def private(part):
        return part in blocked or part.startswith((".env", ".live-", ".focus", ".project-catalog")) or part.endswith((".secret", ".pem", ".key"))
    if any(private(part.casefold()) for part in relative.parts):
        raise ValueError("Percorso riservato")
    if target.is_dir():
        visible = sorted(c.name for c in target.iterdir() if not private(c.name.casefold()))
        return dict(path=str(target), entries=visible[:200], truncated=len(visible) > 200)
    if target.stat().st_size > 256_000:
        raise ValueError("File troppo grande (limite 256 KB); seleziona un estratto")
    text = target.read_text(encoding="utf-8-sig")
    return dict(path=str(target), text=text[:16000], truncated=len(text) > 16000)
