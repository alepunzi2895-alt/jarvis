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
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from core.system_executor import SystemExecutor

_NOTES_DIR = Path(__file__).resolve().parent.parent / "memory" / "projects"
_NOTES_EXCERPT_CHARS = 500


@dataclass(frozen=True)
class ProjectConfig:
    key: str
    label: str
    env_var: str
    notes_file: str


# Isabela/Vino non hanno ancora un path locale in .env (WS_ISABELA/WS_VINO
# assenti) — non li includo qui finche' non lo sono: riportarli sempre come
# "non configurato" non aggiungerebbe informazione.
PROJECTS: list[ProjectConfig] = [
    ProjectConfig("aura", "Aura Ibiza", "WS_AURA", "aura-ibiza.md"),
    ProjectConfig("trading", "TradeFlow AI", "WS_TRADING", "tradeflow-ai.md"),
    ProjectConfig("whitesoul", "Whitesoul Ibiza", "WS_WHITESOUL", "whitesoulibiza.md"),
]


@dataclass
class ProjectStatus:
    key: str
    label: str
    path: str | None
    configured: bool
    branch: str | None = None
    dirty_files: int = 0
    last_commit: str | None = None
    last_commit_ts: int | None = None
    notes: str | None = None
    error: str | None = None
    health_percent: int | None = None


def _compute_health_percent(status: ProjectStatus) -> int | None:
    """Punteggio di "salute" 0-100 da segnali git/note REALI — non e' una
    percentuale di completamento (nessun task tracker esiste per questi
    progetti), e' onestamente etichettato come "salute": albero pulito e
    commit recenti alzano il punteggio, un flag 🔴 nelle note JARVIS o un
    lungo silenzio lo abbassano. Richiesta di Alessandro (2026-09-15): dati
    veri a schermo, non un numero inventato senza base."""
    if not status.configured or status.error:
        return None
    score = 100
    if status.notes and "\U0001F534" in status.notes:
        score -= 50
    score -= min(status.dirty_files * 5, 30)
    if status.last_commit_ts:
        days = (time.time() - status.last_commit_ts) / 86400
        if days > 30:
            score -= 30
        elif days > 14:
            score -= 15
        elif days > 7:
            score -= 5
    return max(0, min(100, score))


def _read_notes_excerpt(notes_file: str) -> str | None:
    try:
        text = (_NOTES_DIR / notes_file).read_text(encoding="utf-8")
    except OSError:
        return None
    idx = text.find("## Stato")
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
    raw_path = os.getenv(cfg.env_var, "").strip()
    if not raw_path or not Path(raw_path).is_dir():
        return ProjectStatus(cfg.key, cfg.label, raw_path or None, configured=False)

    status = ProjectStatus(
        cfg.key, cfg.label, raw_path, configured=True,
        notes=_read_notes_excerpt(cfg.notes_file),
    )

    r = executor.git("status --short --branch", raw_path)
    if not r.ok:
        status.error = (r.stderr or "git status fallito").strip()
        return status

    lines = r.stdout.splitlines()
    if lines and lines[0].startswith("##"):
        status.branch = lines[0][2:].strip().split("...")[0].strip()
        lines = lines[1:]
    status.dirty_files = len([line for line in lines if line.strip()])

    # "%ct" (unix timestamp) accodato con un separatore invece di una
    # seconda chiamata git separata - serve solo per _compute_health_percent,
    # il testo mostrato in /progetti resta "%h %s (%cr)" come sempre.
    log = executor.git('log -1 --format="%h %s (%cr)|%ct"', raw_path)
    if log.ok and log.stdout.strip():
        text, _, ts = log.stdout.strip().rpartition("|")
        status.last_commit = text or log.stdout.strip()
        if ts.isdigit():
            status.last_commit_ts = int(ts)

    status.health_percent = _compute_health_percent(status)
    return status


def check_all(executor: SystemExecutor) -> list[ProjectStatus]:
    return [_check_one(cfg, executor) for cfg in PROJECTS]


def to_json_ready(statuses: list[ProjectStatus]) -> list[dict]:
    """Per il pannello "Stato progetti" della dashboard (JSON su Turso,
    stesso principio del flag "speaking"/previsioni meteo — il browser non
    ha altro modo di leggere git in locale)."""
    return [asdict(s) for s in statuses]


def format_report(statuses: list[ProjectStatus], voice: bool) -> str:
    if voice:
        parts = []
        for s in statuses:
            if not s.configured:
                continue
            if s.error:
                parts.append(f"{s.label}: errore")
                continue
            state = "pulito" if s.dirty_files == 0 else f"{s.dirty_files} modifiche in sospeso"
            flag = " — problema noto" if s.notes and "\U0001F534" in s.notes else ""
            parts.append(f"{s.label}: {state}{flag}")
        if not parts:
            return "Nessun progetto configurato, Signore."
        return f"Stato progetti, Signore — {'; '.join(parts)}."

    lines = ["Stato progetti:", ""]
    for s in statuses:
        if not s.configured:
            lines.append(f"• {s.label}: workspace non configurato.")
            lines.append("")
            continue
        if s.error:
            lines.append(f"• {s.label}: errore git ({s.error[:120]})")
            lines.append("")
            continue
        dirty = "pulito" if s.dirty_files == 0 else f"{s.dirty_files} modifiche non committate"
        branch = f" [{s.branch}]" if s.branch else ""
        lines.append(f"• {s.label}{branch}: {dirty}")
        if s.last_commit:
            lines.append(f"  Ultimo commit: {s.last_commit}")
        if s.notes:
            lines.append(f"  Note JARVIS: {s.notes}")
        lines.append("")
    return "\n".join(lines).strip()
