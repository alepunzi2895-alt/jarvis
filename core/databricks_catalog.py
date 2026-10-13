"""Inventario QAS in sola lettura; nessun endpoint di modifica o avvio job."""
import base64
import json
import re
from datetime import datetime, timedelta, timezone
import requests

from core import databricks as db


def inspect(kind, path="/", item_id="", days=7, page_token=""):
    cfg = db._env_config("qas")
    headers = {"Authorization": f"Bearer {db._get_token('qas')}"}
    params = {}
    if kind == "jobs":
        endpoint, field = "/api/2.2/jobs/list", "jobs"
        params = {"limit": 50}
    elif kind == "runs":
        if not 1 <= int(days) <= 30:
            raise ValueError("Periodo ammesso: 1-30 giorni")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(days))
        endpoint, field = "/api/2.2/jobs/runs/list", "runs"
        params = dict(limit=25, start_time_from=int(start.timestamp()*1000), start_time_to=int(end.timestamp()*1000))
        if item_id:
            params["job_id"] = int(item_id)
    elif kind == "dashboards":
        endpoint, field = "/api/2.0/lakeview/dashboards", "dashboards"
        params = dict(page_size=100, view="DASHBOARD_VIEW_BASIC")
    elif kind == "dashboard":
        if not re.fullmatch(r"[\w-]+", item_id):
            raise ValueError("ID dashboard non valido")
        endpoint, field = f"/api/2.0/lakeview/dashboards/{item_id}", None
    elif kind == "workspace":
        endpoint, field = "/api/2.0/workspace/list", "objects"
        params = dict(path=path)
    elif kind == "notebook":
        endpoint, field = "/api/2.0/workspace/export", None
        params = dict(path=path, format="SOURCE")
    elif kind == "job":
        endpoint, field = "/api/2.2/jobs/get", None
        params = dict(job_id=int(item_id))
    else:
        raise ValueError("Tipo non supportato")
    if page_token:
        if kind not in {"jobs", "runs", "dashboards", "job"}:
            raise ValueError("Paginazione non supportata")
        params["page_token"] = page_token
    response = requests.get(cfg["host"] + endpoint, headers=headers, params=params, timeout=25)
    response.raise_for_status()
    data = response.json()
    result = dict(source="Databricks QAS", observed_at=datetime.now(timezone.utc).isoformat(), kind=kind)
    if kind == "notebook":
        text = base64.b64decode(data.get("content", "")).decode("utf-8")
        return dict(**result, path=path, text=text[:16000], truncated=len(text) > 16000)
    if kind == "dashboard":
        definition = json.loads(data.get("serialized_dashboard") or "{}")
        return dict(**result, name=data.get("display_name"), path=data.get("path"),
                    datasets=definition.get("datasets", []),
                    pages=[dict(name=p.get("name"), display_name=p.get("displayName")) for p in definition.get("pages", [])],
                    notice="Definizione AI/BI, non risultati delle query. Per valori attuali usa query_databricks.")
    if kind == "job":
        settings = data.get("settings", {})
        return dict(**result, job_id=data.get("job_id"), name=settings.get("name"),
                    tasks=[dict(task_key=t.get("task_key"), depends_on=t.get("depends_on"),
                                notebook_path=t.get("notebook_task", {}).get("notebook_path"))
                           for t in settings.get("tasks", [])],
                    next_page_token=data.get("next_page_token"), partial=bool(data.get("next_page_token")))
    rows = data.get(field, [])
    next_token = data.get("next_page_token")
    result.update(count=len(rows), next_page_token=next_token, partial=bool(next_token or data.get("has_more")),
                  scope="Elementi visibili al service principal; elenco non ricorsivo. Ogni pagina e' un campione.")
    if kind == "jobs":
        result["items"] = [dict(job_id=r.get("job_id"), name=r.get("settings", {}).get("name")) for r in rows]
    elif kind == "runs":
        result.update(start=start.isoformat(), end=end.isoformat())
        result["metrics"] = run_metrics(rows)
        result["items"] = [dict(run_id=r.get("run_id"), job_id=r.get("job_id"),
                                start_time=r.get("start_time"), end_time=r.get("end_time"),
                                state=r.get("state"), run_page_url=r.get("run_page_url")) for r in rows]
    elif kind == "dashboards":
        result["items"] = [{k: r.get(k) for k in ("dashboard_id", "display_name", "lifecycle_state", "create_time")} for r in rows]
    else:
        result["items"] = [{k: r.get(k) for k in ("path", "object_type", "language", "object_id")} for r in rows]
    return result


def run_metrics(rows):
    # Denominatore dichiarato: solo esiti terminali noti; attivi e sconosciuti separati.
    outcomes = [(r.get("state") or {}).get("result_state") or
                ((r.get("status") or {}).get("termination_details") or {}).get("code") for r in rows]
    succeeded = sum(s == "SUCCESS" for s in outcomes)
    failed = sum(s in {"FAILED", "TIMEDOUT", "INTERNAL_ERROR", "RUN_EXECUTION_ERROR"} for s in outcomes)
    canceled = sum(s in {"CANCELED", "CANCELLED"} for s in outcomes)
    known = succeeded + failed + canceled
    durations = [(r["end_time"]-r["start_time"])/1000 for r in rows
                 if (r.get("end_time") or 0) > (r.get("start_time") or 0) > 0]
    return dict(sample_runs=len(rows), succeeded=succeeded, failed=failed, canceled=canceled,
                active_or_unknown=len(rows)-known, terminal_known=known,
                failure_rate_percent=round(100*failed/known, 1) if known else None,
                mean_elapsed_seconds=round(sum(durations)/len(durations), 1) if durations else None,
                durations_count=len(durations), notice="Statistiche della sola pagina, durata wall-clock; non CPU/costi.")
