"""
JARVIS — stato dei repository GitHub reali dell'utente.

Richiesta esplicita di Alessandro (2026-09-15): "andrebbe integrato il mio
GitHub e il mio vercel per vedere tutti i progetti e gli status". A
differenza di core/project_status.py (che legge solo i 3 workspace con un
path locale configurato in .env — aura/trading/whitesoul), questo legge
DIRETTAMENTE dall'API di GitHub: mostra ogni repository che possiede
davvero, non solo quelli clonati su questo PC (VMScout, property_scout,
ConciergeFlow, ecc. non hanno mai avuto un path locale configurato qui).

Nessun token -> lista vuota, mai un'eccezione (stesso principio di
core/weather.py per rete/config assente).
"""

from __future__ import annotations

import os

import requests

_TIMEOUT = 8
_API = "https://api.github.com"


def _token() -> str | None:
    return os.getenv("GITHUB_TOKEN", "").strip() or None


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "jarvis-dashboard",
    }


def _fetch_last_commit(full_name: str, branch: str, token: str) -> dict | None:
    try:
        r = requests.get(
            f"{_API}/repos/{full_name}/commits/{branch}",
            headers=_headers(token),
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        commit = r.json()
        message = (commit.get("commit", {}).get("message") or "").splitlines()
        return {
            "sha": (commit.get("sha") or "")[:7],
            "message": message[0][:120] if message else "",
            "date": commit.get("commit", {}).get("author", {}).get("date"),
        }
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def _summarize(repo: dict, token: str) -> dict:
    full_name = repo.get("full_name", "")
    branch = repo.get("default_branch")
    return {
        "name": repo.get("name"),
        "full_name": full_name,
        "private": bool(repo.get("private")),
        "url": repo.get("html_url"),
        "description": repo.get("description"),
        "default_branch": branch,
        "pushed_at": repo.get("pushed_at"),
        "open_issues": repo.get("open_issues_count"),
        "last_commit": _fetch_last_commit(full_name, branch, token) if branch else None,
    }


def list_repos(include_forks: bool = False, max_repos: int = 30) -> list[dict]:
    """Repository posseduti dall'utente (non organizzazioni/collaborazioni),
    ordinati per ultimo push, ognuno con l'ultimo commit reale (una chiamata
    in piu' per repo — trascurabile: un PAT ha 5000 richieste/ora, qui ne
    bastano al massimo max_repos+1)."""
    token = _token()
    if not token:
        return []
    try:
        r = requests.get(
            f"{_API}/user/repos",
            headers=_headers(token),
            params={"per_page": 100, "sort": "pushed", "affiliation": "owner"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        repos = r.json()
    except (requests.RequestException, ValueError):
        return []

    out: list[dict] = []
    for repo in repos:
        if repo.get("archived"):
            continue
        if repo.get("fork") and not include_forks:
            continue
        out.append(_summarize(repo, token))
        if len(out) >= max_repos:
            break
    return out
