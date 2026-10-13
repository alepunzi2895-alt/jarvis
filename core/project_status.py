"""
JARVIS — stato dei progetti attivi: git status/log locali + estratto delle
note JARVIS gia' in memory/projects/. Sola lettura (solo i sottocomandi
"status"/"log", in whitelist di SystemExecutor — mai una scrittura).

Punto unico richiamato da piu' entry point (bot.py: /progetti e digest
mattutino; core/intents.py: comando rapido testo/voce) — stesso principio
gia' in uso nel resto del repo: la logica vive qui una volta sola, i
chiamanti restano chiamate sottili.
"""

from __future__ import annotations

import os
import subprocess
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path

from core.system_executor import SystemExecutor
from core import projects

_NOTES_DIR = Path(__file__).resolve().parent.parent / "memory" / "projects"
_NOTES_EXCERPT_CHARS = 500
_snapshot_cache = {"key": None, "ts": 0.0, "values": []}
_snapshot_lock = threading.Lock()


@dataclass(frozen=True)
class ProjectConfig:
    key: str
    label: str
    env_var: str
    notes_file: str


# Vista aggiornata a ogni lettura, anche per chiamanti storici.
class ProjectCatalog:
    def __iter__(self):
        return iter(projects.catalog())


PROJECTS = ProjectCatalog()


@dataclass
class ProjectStatus:
    key: str
    label: str
    path: str | None
    configured: bool
    branch: str | None = None
    dirty_files: int = 0
    last_commit: str | None = None
    notes: str | None = None
    error: str | None = None


def _read_notes_excerpt(notes_file: str) -> str | None:
    try:
        text = (_NOTES_DIR / notes_file).read_text(encoding="utf-8")
    except OSError:
        return None
    idx = text.rfind("## Stato")
    if idx == -1:
        return None
    excerpt = text[idx:]
    nxt = excerpt.find("\n## ", len("## Stato"))
    if nxt != -1:
        excerpt = excerpt[:nxt]
    excerpt = excerpt.strip()
    if len(excerpt) > _NOTES_EXCERPT_CHARS:
        excerpt = excerpt[:_NOTES_EXCERPT_CHARS].rstrip() + "…"
    return excerpt


def _check_one(cfg: ProjectConfig, executor: SystemExecutor) -> ProjectStatus:
    raw_path = getattr(cfg, "path", None) or os.getenv(cfg.env_var, "").strip()
    if not raw_path or not Path(raw_path).is_dir():
        return ProjectStatus(cfg.key, cfg.label, raw_path or None, configured=False,
                             notes=_read_notes_excerpt(cfg.notes_file))

    status = ProjectStatus(
        cfg.key, cfg.label, raw_path, configured=True,
        notes=_read_notes_excerpt(cfg.notes_file),
    )

    # La scoperta concede solo lettura di metadati Git, mai nuovi permessi
    # al SystemExecutor per scrivere/eseguire comandi in questi progetti.
    if isinstance(cfg, projects.Project):
        if not (Path(raw_path) / ".git").exists():
            return status
        try:
            r = projects.git_read(raw_path, "status", "--short", "--branch")
            r.ok = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            status.error = str(exc)
            return status
    else:
        r = executor.git("status --short --branch", raw_path)
    if not r.ok:
        status.error = (r.stderr or "git status fallito").strip()
        return status

    lines = r.stdout.splitlines()
    if lines and lines[0].startswith("##"):
        status.branch = lines[0][2:].strip().split("...")[0].strip()
        lines = lines[1:]
    status.dirty_files = len([line for line in lines if line.strip()])

    if isinstance(cfg, projects.Project):
        try:
            log = projects.git_read(raw_path, "log", "-1", "--format=%h %s (%cr)")
            log.ok = log.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return status
    else:
        log = executor.git('log -1 --format="%h %s (%cr)"', raw_path)
    if log.ok and log.stdout.strip():
        status.last_commit = log.stdout.strip()

    return status


def check_all(executor: SystemExecutor) -> list[ProjectStatus]:
    configs = list(PROJECTS)
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda cfg: _check_one(cfg, executor), configs))


def cached_check_all(executor: SystemExecutor) -> list[ProjectStatus]:
    # Riutilizza la scansione del widget nei tool e nelle richieste vocali.
    configs = list(PROJECTS)
    key = (id(executor), tuple((p.key, getattr(p, "path", None), p.notes_file,
                               os.getenv(p.env_var, "")) for p in configs))
    with _snapshot_lock:
        if _snapshot_cache["key"] != key or time.monotonic() - _snapshot_cache["ts"] >= 30:
            values = check_all(executor)
            _snapshot_cache.update(key=key, ts=time.monotonic(), values=values)
        return list(_snapshot_cache["values"])


def is_overview_request(prompt: str) -> bool:
    prompt = re.sub(r"^\s*jarvis[, :]+", "", prompt, flags=re.I).strip()
    return bool(re.fullmatch(
        r"(?:come (?:vanno|stanno|sono messi) (?:i |i miei |tutti i )?progetti|"
        r"(?:stato|situazione|aggiornamenti|novit[aà]) (?:dei |sui |sui miei )?progetti)[?.! ]*",
        prompt, re.I))


def attention_report(statuses: list[ProjectStatus]) -> dict:
    highlights = []
    for s in statuses:
        if s.error:
            highlights.append((0, s.key, f"{s.label}: stato Git non verificabile, controlla l'accesso al repository."))
        elif s.configured and s.notes and "🔴" in s.notes:
            highlights.append((1, s.key, f"{s.label}: una nota storica segnala un problema noto, ancora da verificare."))
        elif s.configured and s.dirty_files:
            highlights.append((2, s.key, f"{s.label}: {s.dirty_files} file modificati da rivedere prima del prossimo commit."))
    highlights.sort(key=lambda item: (item[0], item[1]))
    verified = sum(bool(s.branch) and not s.error for s in statuses)
    if highlights:
        sentences = [item[2] for item in highlights[:2]]
        sentences[0] = "Signore, " + sentences[0]
    elif verified:
        sentences = ["Nei repository controllati non emergono modifiche locali o errori di lettura, Signore."]
    else:
        sentences = ["Non ho ancora uno stato Git verificabile dei progetti, Signore."]
    return dict(reported_at=datetime.now().isoformat(), checked=len(statuses), verified_repositories=verified,
                highlights=[dict(project=key, text=text) for _, key, text in highlights[:2]],
                additional_items=max(0, len(highlights)-2), sentences=sentences,
                scope="Snapshot Git locale, massimo 30 secondi. Modifiche non committate non sono guasti. "
                      "Le note sono storiche; deploy, metriche di business e Databricks richiedono verifiche dedicate.")


def check_one_by_key(key: str, executor: SystemExecutor) -> ProjectStatus | None:
    """Stato di una chiave/alias del catalogo, None se sconosciuta."""
    key = projects.canonical(key or "")
    cfg = next((c for c in PROJECTS if c.key == key), None)
    return _check_one(cfg, executor) if cfg else None


def to_json_ready(statuses: list[ProjectStatus]) -> list[dict]:
    """Per il pannello "Stato progetti" della dashboard (JSON su Turso,
    stesso principio del flag "speaking"/previsioni meteo — il browser non
    ha altro modo di leggere git in locale)."""
    return [asdict(s) for s in statuses]


def format_report(statuses: list[ProjectStatus], voice: bool) -> str:
    if voice:
        return " ".join(attention_report(statuses)["sentences"])

    lines = ["Stato progetti:", ""]
    for s in statuses:
        if not s.configured:
            lines.append(f"• {s.label}: percorso locale non configurato; disponibile in memoria/registro.")
            lines.append("")
            continue
        if s.error:
            lines.append(f"• {s.label}: errore git ({s.error[:120]})")
            lines.append("")
            continue
        dirty = ("cartella senza Git" if not s.branch else
                 "pulito" if s.dirty_files == 0 else f"{s.dirty_files} modifiche non committate")
        branch = f" [{s.branch}]" if s.branch else ""
        lines.append(f"• {s.label}{branch}: {dirty}")
        if s.last_commit:
            lines.append(f"  Ultimo commit: {s.last_commit}")
        if s.notes:
            lines.append(f"  Note JARVIS: {s.notes}")
        lines.append("")
    return "\n".join(lines).strip()
