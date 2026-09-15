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
    return {
        "name": project.get("name"),
        "url": f"https://{latest['url']}" if latest.get("url") else None,
        "state": latest.get("readyState"),  # READY | ERROR | BUILDING | QUEUED | CANCELED
        "updated_at": latest.get("createdAt"),
        "repo": (project.get("link") or {}).get("repo"),
    }


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
