"""
JARVIS — vista unificata GitHub + Vercel per il pannello "Stato progetti"
della dashboard (richiesta di Alessandro, 2026-09-15). Un repository GitHub
e un progetto Vercel vengono accoppiati quando il campo "repo" collegato al
progetto Vercel corrisponde (case-insensitive) al nome del repository —
Vercel lo espone gia' esplicitamente (project.link.repo), non serve
indovinare per somiglianza di stringa.
"""

from __future__ import annotations

from core import github_status, vercel_status


def build_remote_status() -> dict:
    repos = github_status.list_repos()
    projects = vercel_status.list_projects()

    by_repo = {(p.get("repo") or "").lower(): p for p in projects if p.get("repo")}
    matched_names = set()

    entries = []
    for repo in repos:
        name = (repo.get("name") or "").lower()
        vercel = by_repo.get(name)
        if vercel:
            matched_names.add(name)
        entries.append({"github": repo, "vercel": vercel})

    # Progetti Vercel senza un repository GitHub corrispondente tra quelli
    # letti sopra (es. non piu' collegato, o repo di un altro account) —
    # mostrati comunque, non silenziosamente persi.
    for p in projects:
        repo_name = (p.get("repo") or "").lower()
        if repo_name and repo_name not in matched_names:
            entries.append({"github": None, "vercel": p})

    return {"entries": entries}
