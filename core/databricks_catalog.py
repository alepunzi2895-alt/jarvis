"""Inventario Databricks in sola lettura: solo richieste GET, nessun endpoint
di modifica o avvio job. QAS completo. PRD (2026-10-14, richiesta esplicita di
Alessandro: "analizzare piu' i job di PRD" e confrontare le dashboard
pubblicate) limitato ai metadati di job, run e dashboard: niente notebook o
cartelle PRD. SQL e Genie su PRD restano sul percorso con conferma di
core/databricks.py."""
import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import requests

from core import databricks as db

_SOURCES = {"qas": "Databricks QAS", "prd": "Databricks PRD"}
_PRD_KINDS = {"jobs", "runs", "runs_summary", "job", "dashboards", "dashboard"}
# 25 run per pagina (massimo accettato dall'API): 40 pagine = 1000 run.
_MAX_RUN_PAGES = 40
_MAX_DASHBOARD_PAGES = 10
_FAILED = {"FAILED", "TIMEDOUT", "INTERNAL_ERROR", "RUN_EXECUTION_ERROR"}
_CANCELED = {"CANCELED", "CANCELLED"}
_ENV_TOKENS = {"qas", "prd", "prod"}


def _client(env):
    if env not in _SOURCES:
        raise ValueError("Ambiente ammesso: qas o prd")
    cfg = db._env_config(env)
    return cfg["host"], {"Authorization": f"Bearer {db._get_token(env)}"}


def _get(host, headers, endpoint, params=None):
    response = requests.get(host + endpoint, headers=headers, params=params or {}, timeout=25)
    response.raise_for_status()
    return response.json()


def _observed(env, kind):
    return dict(source=_SOURCES[env], env=env, observed_at=datetime.now(timezone.utc).isoformat(), kind=kind)


def _period(days):
    if not 1 <= int(days) <= 30:
        raise ValueError("Periodo ammesso: 1-30 giorni")
    end = datetime.now(timezone.utc)
    return end - timedelta(days=int(days)), end


def _local(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone().isoformat(timespec="minutes") if ms else None


def inspect(kind, path="/", item_id="", days=7, page_token="", env="qas"):
    if env == "prd" and kind not in _PRD_KINDS:
        raise ValueError("Su PRD solo metadati di job, run e dashboard (sola lettura)")
    if kind == "runs_summary":
        return runs_summary(env, days, item_id)
    if kind == "compare_dashboards":
        return compare_dashboards()
    host, headers = _client(env)
    params = {}
    if kind == "jobs":
        endpoint, field = "/api/2.2/jobs/list", "jobs"
        params = {"limit": 50}
    elif kind == "runs":
        start, end = _period(days)
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
    data = _get(host, headers, endpoint, params)
    result = _observed(env, kind)
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


def _outcome(row):
    return ((row.get("state") or {}).get("result_state") or
            ((row.get("status") or {}).get("termination_details") or {}).get("code"))


def _elapsed(row):
    start, end = row.get("start_time") or 0, row.get("end_time") or 0
    return (end - start) / 1000 if end > start > 0 else None


def run_metrics(rows):
    # Denominatore dichiarato: solo esiti terminali noti; attivi e sconosciuti separati.
    outcomes = [_outcome(r) for r in rows]
    succeeded = sum(s == "SUCCESS" for s in outcomes)
    failed = sum(s in _FAILED for s in outcomes)
    canceled = sum(s in _CANCELED for s in outcomes)
    known = succeeded + failed + canceled
    durations = [d for d in map(_elapsed, rows) if d is not None]
    return dict(sample_runs=len(rows), succeeded=succeeded, failed=failed, canceled=canceled,
                active_or_unknown=len(rows)-known, terminal_known=known,
                failure_rate_percent=round(100*failed/known, 1) if known else None,
                mean_elapsed_seconds=round(sum(durations)/len(durations), 1) if durations else None,
                durations_count=len(durations), notice="Statistiche della sola pagina, durata wall-clock; non CPU/costi.")


def runs_summary(env="prd", days=7, job_id=""):
    """Tutte le pagine del periodo (fino a _MAX_RUN_PAGES) aggregate nel codice:
    una sola chiamata tool invece di una per pagina, conteggi non affidati al modello."""
    start, end = _period(days)
    host, headers = _client(env)
    params = dict(limit=25, start_time_from=int(start.timestamp()*1000), start_time_to=int(end.timestamp()*1000))
    if job_id:
        params["job_id"] = int(job_id)
    rows, pages, token = [], 0, ""
    while pages < _MAX_RUN_PAGES:
        data = _get(host, headers, "/api/2.2/jobs/runs/list", dict(params, page_token=token) if token else params)
        rows += data.get("runs", [])
        pages += 1
        token = data.get("next_page_token")
        if not token:
            break
    jobs = {}
    for row in rows:
        job = jobs.setdefault(row.get("job_id"), dict(job_id=row.get("job_id"), name=row.get("run_name"), rows=[]))
        job["rows"].append(row)
    summary = []
    for job in jobs.values():
        job_rows = job.pop("rows")
        metrics = run_metrics(job_rows)
        durations = [d for d in map(_elapsed, job_rows) if d is not None]
        failures = sorted((r for r in job_rows if _outcome(r) in _FAILED), key=lambda r: r.get("start_time") or 0)
        last = failures[-1] if failures else None
        summary.append(dict(
            **job, runs=len(job_rows), succeeded=metrics["succeeded"], failed=metrics["failed"],
            canceled=metrics["canceled"], active_or_unknown=metrics["active_or_unknown"],
            failure_rate_percent=metrics["failure_rate_percent"], mean_elapsed_seconds=metrics["mean_elapsed_seconds"],
            max_elapsed_seconds=round(max(durations), 1) if durations else None,
            last_failure=dict(run_id=last.get("run_id"), start=_local(last.get("start_time")),
                              message=((last.get("state") or {}).get("state_message") or "")[:200],
                              run_page_url=last.get("run_page_url")) if last else None))
    summary.sort(key=lambda j: (-(j["failed"] or 0), -(j["max_elapsed_seconds"] or 0)))
    overall = run_metrics(rows)
    overall["notice"] = "Tutte le run lette nel periodo, durata wall-clock; non CPU/costi."
    complete = not token
    starts = [r["start_time"] for r in rows if r.get("start_time")]
    return dict(**_observed(env, "runs_summary"), period_start=start.isoformat(), period_end=end.isoformat(),
                first_run=_local(min(starts)) if starts else None, last_run=_local(max(starts)) if starts else None,
                pages_read=pages, complete=complete,
                coverage="Tutte le run del periodo visibili al service principal." if complete else
                f"Parziale: lette solo le prime {len(rows)} run ({pages} pagine), periodo non coperto per intero.",
                overall=overall, jobs=summary[:60], jobs_omitted=max(0, len(summary) - 60))


def _norm_name(name):
    # Toglie l'ambiente solo come primo/ultimo termine ("[QAS] Sales", "Sales PRD"):
    # rimuoverlo ovunque fonderebbe dashboard diverse.
    tokens = [t for t in re.split(r"[\W_]+", (name or "").lower()) if t]
    if tokens and tokens[0] in _ENV_TOKENS:
        tokens = tokens[1:]
    if tokens and tokens[-1] in _ENV_TOKENS:
        tokens = tokens[:-1]
    return " ".join(tokens)


def _dashboards_with_publication(env):
    # Una Session sequenziale: 8 richieste parallele davano SSLError dal proxy
    # aziendale (2026-10-14) e 100 s persi; in serie ~0,1 s a richiesta.
    host, headers = _client(env)
    session = requests.Session()
    session.headers.update(headers)

    def get(endpoint, params=None):
        # Le API Lakeview rispondono 429 se interrogate di frequente: rispetta
        # Retry-After (massimo 10 s) per tre tentativi.
        for attempt in range(3):
            response = session.get(host + endpoint, params=params or {}, timeout=25)
            if response.status_code != 429 or attempt == 2:
                break
            try:
                wait = float(response.headers.get("Retry-After", 2))
            except ValueError:
                wait = 2.0
            time.sleep(min(max(wait, 1.0), 10.0))
        response.raise_for_status()
        return response.json()

    rows, token = [], ""
    for _ in range(_MAX_DASHBOARD_PAGES):
        params = dict(page_size=100, view="DASHBOARD_VIEW_BASIC")
        if token:
            params["page_token"] = token
        data = get("/api/2.0/lakeview/dashboards", params)
        rows += data.get("dashboards", [])
        token = data.get("next_page_token")
        if not token:
            break
    items = []
    for row in rows:
        if row.get("lifecycle_state", "ACTIVE") != "ACTIVE":
            continue
        item = dict(dashboard_id=row.get("dashboard_id"), name=row.get("display_name"))
        try:
            # L'elenco BASIC non ha path e data di modifica della bozza.
            detail = get(f"/api/2.0/lakeview/dashboards/{row['dashboard_id']}")
            item.update(path=detail.get("path"), draft_updated=detail.get("update_time"))
            try:
                published = get(f"/api/2.0/lakeview/dashboards/{row['dashboard_id']}/published")
                item.update(published=True, published_at=published.get("revision_create_time"))
            except requests.HTTPError as error:
                if getattr(error.response, "status_code", None) != 404:
                    raise
                item.update(published=False, published_at=None)
        except requests.RequestException as error:
            item.update(published=None, published_at=None, error=f"{type(error).__name__}: {str(error)[:120]}")
        items.append(item)
    return items, bool(token)


def _status(qas, prd):
    if not prd:
        return "solo_qas"
    if not qas:
        return "solo_prd"
    if prd["published"] is False:
        return "prd_non_pubblicata"
    if qas.get("published_at") and prd.get("published_at") and qas["published_at"] > prd["published_at"]:
        return "qas_pubblicata_dopo_prd"
    if prd.get("published_at") and (prd.get("draft_updated") or "") > prd["published_at"]:
        return "prd_bozza_non_pubblicata"
    return "allineata"


def compare_dashboards():
    """Dashboard AI/BI PRD contro QAS, abbinate per nome normalizzato."""
    result = dict(source="Databricks QAS+PRD", observed_at=datetime.now(timezone.utc).isoformat(), kind="compare_dashboards",
                  notice="Stato di pubblicazione da API Lakeview /published, abbinamento per nome senza "
                         "qas/prd/prod iniziale o finale. Non confronta query, dati o permessi.")
    def load(env):
        try:
            return _dashboards_with_publication(env), None
        except Exception as error:  # noqa: BLE001 — un ambiente non raggiungibile non nasconde l'altro
            return ([], False), f"{type(error).__name__}: {str(error)[:200]}"

    lists = {}
    # Un solo thread per host: i due ambienti in parallelo, richieste in serie.
    with ThreadPoolExecutor(max_workers=2) as pool:
        for env, ((items, truncated), error) in zip(("qas", "prd"), pool.map(load, ("qas", "prd"))):
            lists[env] = items
            if error:
                result[f"{env}_error"] = error
            else:
                result.update({f"{env}_count": len(items), f"{env}_partial": truncated})
    groups = {}
    for env, items in lists.items():
        for item in items:
            groups.setdefault(_norm_name(item["name"]), {}).setdefault(env, []).append(item)
    rows = []
    for key, envs in sorted(groups.items()):
        qas_items, prd_items = envs.get("qas", []), envs.get("prd", [])
        qas = qas_items[0] if qas_items else None
        prd = prd_items[0] if prd_items else None
        row = dict(name=(prd or qas)["name"], status=_status(qas, prd), qas=qas, prd=prd)
        if prd and prd.get("published_at") and (prd.get("draft_updated") or "") > prd["published_at"]:
            row["prd_bozza_piu_recente"] = True
        if len(qas_items) > 1 or len(prd_items) > 1:
            row["duplicates"] = dict(qas=len(qas_items), prd=len(prd_items))
        rows.append(row)
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    order = ["qas_pubblicata_dopo_prd", "prd_non_pubblicata", "prd_bozza_non_pubblicata", "solo_qas", "solo_prd", "allineata"]
    rows.sort(key=lambda r: order.index(r["status"]))
    return dict(**result, counts=counts, dashboards=rows)
