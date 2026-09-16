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
    notes: str | None = None
    error: str | None = None


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

    log = executor.git('log -1 --format="%h %s (%cr)"', raw_path)
    if log.ok and log.stdout.strip():
        status.last_commit = log.stdout.strip()

    return status


def check_all(executor: SystemExecutor) -> list[ProjectStatus]:
    return [_check_one(cfg, executor) for cfg in PROJECTS]


def check_one_by_key(key: str, executor: SystemExecutor) -> ProjectStatus | None:
    """Per il tool Claude "get_project_status" (core/claude_bridge.py,
    2026-09-16): "quando chiedo lo stato mi deve chiedere di quale
    progetto" — un solo git status/log invece dei 3 di check_all(), None se
    la chiave non e' tra i progetti noti (aura/trading/whitesoul)."""
    key = (key or "").strip().lower()
    cfg = next((c for c in PROJECTS if c.key == key), None)
    return _check_one(cfg, executor) if cfg else None


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
