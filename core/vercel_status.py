"""
JARVIS — stato dei progetti Vercel reali dell'utente (deploy piu' recente:
pronto/in build/in errore). Stessa richiesta/motivazione di
core/github_status.py (2026-09-15).

ATTENZIONE (2026-09-15): scritto in attesa del token Vercel di Alessandro —
i nomi dei campi di /v9/projects sotto sono presi dalla documentazione
pubblica dell'API, non ancora verificati con una chiamata reale come
core/github_status.py (quello si', con dati veri). Va ri-controllato con un
test dal vivo appena arriva il token, PRIMA di dire che "funziona" — stessa
regola che Alessandro ha chiesto esplicitamente oggi per l'errore Outlook.

Nessun token -> lista vuota, mai un'eccezione (stesso principio di
core/weather.py per rete/config assente).
"""

from __future__ import annotations

import os

import json
import requests

_TIMEOUT = 8
_API = "https://api.vercel.com"


def _token() -> str | None:
    return os.getenv("VERCEL_TOKEN", "").strip() or None


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _summarize(project: dict) -> dict:
    deployments = project.get("latestDeployments") or project.get("targets", {}).get("production") or []
    if isinstance(deployments, dict):
        deployments = [deployments]
    latest = deployments[0] if deployments else {}
    name = project.get("name")
    # Dominio custom se presente (alias), altrimenti il default <nome>.vercel.app
    aliases = [a.get("domain") for a in (project.get("alias") or []) if isinstance(a, dict) and a.get("domain")]
    domain = aliases[0] if aliases else (f"{name}.vercel.app" if name else None)
    return {
        "name": name,
        "domain": domain,
        "domain_url": f"https://{domain}" if domain else None,
        "url": f"https://{latest['url']}" if latest.get("url") else None,
        "state": latest.get("readyState"),  # READY | ERROR | BUILDING | QUEUED | CANCELED
        "updated_at": latest.get("createdAt"),
        "message": (latest.get("meta") or {}).get("githubCommitMessage") or "",
        "repo": (project.get("link") or {}).get("repo"),
    }


_USAGE_CACHE = {"at": 0.0, "data": {}}
USAGE_TTL_SEC = 3600


def usage_gb_by_project(days: int = 30) -> dict:
    """GB di trasferimento per progetto negli ultimi `days` giorni, dalle righe di fatturazione Vercel
    (Fast Data Transfer + Fast Origin Transfer, taggate con ProjectName). Cache di un'ora."""
    import time
    from datetime import datetime, timedelta, timezone
    token = _token()
    if not token:
        return {}
    if time.time() - _USAGE_CACHE["at"] < USAGE_TTL_SEC and _USAGE_CACHE["data"]:
        return _USAGE_CACHE["data"]
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    params = {"from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "to": now.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    team_id = os.getenv("VERCEL_TEAM_ID", "").strip()
    if team_id:
        params["teamId"] = team_id
    totals: dict = {}
    try:
        r = requests.get(f"{_API}/v1/billing/charges", headers=_headers(token), params=params, timeout=60)
        r.raise_for_status()
        for line in r.text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("ServiceName") not in ("Fast Data Transfer", "Fast Origin Transfer"):
                continue
            name = (row.get("Tags") or {}).get("ProjectName")
            if not name:
                continue
            item = totals.setdefault(name, {"gb": 0.0})
            item["gb"] += float(row.get("ConsumedQuantity") or 0)
    except (requests.RequestException, ValueError):
        return _USAGE_CACHE["data"]  # niente dato nuovo: resta l'ultimo valore buono
    data = {name: round(item["gb"], 2) for name, item in totals.items()}
    _USAGE_CACHE.update(at=time.time(), data=data)
    return data


def list_projects(max_projects: int = 30) -> list[dict]:
    token = _token()
    if not token:
        return []
    try:
        params: dict = {"limit": max_projects}
        team_id = os.getenv("VERCEL_TEAM_ID", "").strip()
        if team_id:
            params["teamId"] = team_id
        r = requests.get(
            f"{_API}/v9/projects",
            headers=_headers(token),
            params=params,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        projects = r.json().get("projects") or []
    except (requests.RequestException, ValueError, KeyError):
        return []

    return [_summarize(p) for p in projects[:max_projects]]
