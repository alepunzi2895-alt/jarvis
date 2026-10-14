"""Sessioni Claude Code e Codex aperte da Alessandro (VS Code, terminale, app
Codex), lette in sola lettura dai transcript locali.

core/coding_tasks.py vede solo i lavori avviati da JARVIS: il 2026-10-14
JARVIS rispondeva "nessun lavoro attivo" mentre Alessandro lavorava in
Claude Code. Qui si leggono solo la coda dei file e pochi campi (progetto,
branch, titolo, ultima richiesta, ultima risposta, stato); stringhe lunghe
tipo token vengono oscurate prima di uscire dal modulo.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
CODEX_DIR = Path.home() / ".codex" / "sessions"
_TAIL_BYTES = 400_000
_WORKING_SEC = 120
_SECRET_RE = re.compile(r"[A-Za-z0-9_\-]{32,}")


def _clip(text, limit=400):
    text = _SECRET_RE.sub("[oscurato]", " ".join(str(text or "").split()))
    return text[:limit] + ("…" if len(text) > limit else "")


def _tail(path):
    with open(path, "rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - _TAIL_BYTES))
        lines = handle.read().decode("utf-8", "replace").splitlines()
    if size > _TAIL_BYTES:
        lines = lines[1:]  # prima riga tagliata a meta'
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def _first(path):
    with open(path, "rb") as handle:
        try:
            return json.loads(handle.readline().decode("utf-8", "replace"))
        except ValueError:
            return {}


def _start_cwd(path):
    """Cartella in cui e' partita la sessione: il cwd degli ultimi record segue
    i cd dentro sottocartelle (es. "refs") e non dice piu' il progetto."""
    with open(path, "rb") as handle:
        for line in handle.read(_TAIL_BYTES).decode("utf-8", "replace").splitlines():
            try:
                cwd = json.loads(line).get("cwd")
            except (ValueError, AttributeError):
                continue
            if cwd:
                return cwd
    return None


def _texts(content):
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") in {"text", "output_text"})


def _claude(path, age):
    records = _tail(path)
    info = next((r for r in reversed(records) if r.get("cwd")), {})
    title = next((r.get("aiTitle") for r in reversed(records) if r.get("type") == "ai-title"), None)
    prompt = next((r.get("lastPrompt") for r in reversed(records) if r.get("type") == "last-prompt"), None)
    if not prompt:
        prompt = next((_texts(r["message"].get("content")) for r in reversed(records)
                       if r.get("type") == "user" and isinstance((r.get("message") or {}).get("content"), str)), "")
    answer = next((_texts(r["message"].get("content")) for r in reversed(records)
                   if r.get("type") == "assistant" and _texts((r.get("message") or {}).get("content")).strip()), "")
    last = next((r for r in reversed(records) if r.get("type") in {"user", "assistant"}), {})
    if last.get("type") == "assistant" and (last.get("message") or {}).get("stop_reason") == "end_turn":
        state = "in attesa di Alessandro"
    elif age <= _WORKING_SEC:
        state = "al lavoro"
    else:
        state = "ferma a meta' (interrotta o in attesa di un permesso)"
    client = next((r.get("entrypoint") for r in reversed(records) if r.get("entrypoint")), None)
    return dict(provider="claude", client=client, cwd=_start_cwd(path) or info.get("cwd"),
                branch=info.get("gitBranch"), title=title, state=state,
                last_prompt=_clip(prompt), last_answer=_clip(answer, 600))


def _codex(path, age):
    meta = (_first(path).get("payload") or {})
    events = [r.get("payload") or {} for r in _tail(path) if r.get("type") == "event_msg"]
    prompt = next((e.get("message") for e in reversed(events) if e.get("type") == "user_message"), "")
    answer = next((e.get("message") for e in reversed(events)
                   if e.get("type") == "agent_message" and not str(e.get("message", "")).startswith("<")), "")
    turn = next((e.get("type") for e in reversed(events) if e.get("type") in {"task_started", "task_complete"}), None)
    if turn == "task_complete":
        state = "in attesa di Alessandro"
    elif age <= _WORKING_SEC:
        state = "al lavoro"
    else:
        state = "ferma a meta' (interrotta o in attesa di un permesso)"
    return dict(provider="codex", client=meta.get("originator") or meta.get("source"), cwd=meta.get("cwd"),
                branch=None, title=None, state=state, last_prompt=_clip(prompt), last_answer=_clip(answer, 600))


def recent_sessions(hours=6, limit=8, exclude_ids=()):
    """Sessioni modificate nelle ultime `hours` ore, piu' recenti prima."""
    now = datetime.now(timezone.utc).timestamp()
    found = []
    for provider, root, pattern in (("claude", CLAUDE_DIR, "*/*.jsonl"), ("codex", CODEX_DIR, "*/*/*/*.jsonl")):
        if not root.exists():
            continue
        for path in root.glob(pattern):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime <= hours * 3600:
                found.append((mtime, provider, path))
    sessions = []
    for mtime, provider, path in sorted(found, reverse=True):
        session_id = path.stem.split("rollout-")[-1][-36:]
        if session_id in exclude_ids:
            continue
        try:
            item = (_claude if provider == "claude" else _codex)(path, now - mtime)
        except OSError:
            continue
        cwd = item.get("cwd") or ""
        # Prove automatiche di JARVIS nelle cartelle temporanee: non sono lavoro di Alessandro.
        if "\\Temp\\" in cwd or "coding-proof" in cwd:
            continue
        item.update(session_id=session_id, project=Path(cwd).name if cwd else None,
                    updated_at=datetime.fromtimestamp(mtime, timezone.utc).astimezone().isoformat(timespec="minutes"),
                    minutes_ago=round((now - mtime) / 60))
        sessions.append(item)
        if len(sessions) >= limit:
            break
    return sessions
