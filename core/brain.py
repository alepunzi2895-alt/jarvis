"""
JARVIS — second brain: memoria a lungo termine che Claude consulta e alimenta da solo.

Due sole operazioni pubbliche, entrambe sincrone/bloccanti (il chiamante in
core/claude_bridge.py le gira su thread con asyncio.to_thread, stesso pattern di
core/web_bridge.py):

- fetch_context(workspace): nodi/relazioni rilevanti, formattati per il prompt.
- extract_and_store(result_text, workspace): estrae il blocco ```brain``` finale
  (se Claude lo ha emesso), lo scrive su Turso, ritorna il testo ripulito.
"""

import json
import re
import uuid

from core import turso

BRAIN_BLOCK_RE = re.compile(r"```brain\s*\n(.*?)\n```", re.DOTALL)

CONTEXT_LIMIT = 40

_bootstrapped = False


def _bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    turso.execute_batch(
        [
            (
                """CREATE TABLE IF NOT EXISTS brain_nodes (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    label_key TEXT NOT NULL UNIQUE,
                    summary TEXT,
                    workspace TEXT,
                    tags TEXT,
                    hits INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )""",
                None,
            ),
            (
                """CREATE TABLE IF NOT EXISTS brain_edges (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, target_id, relation)
                )""",
                None,
            ),
        ]
    )
    _bootstrapped = True


def _get_node_id(label_key: str) -> str | None:
    rows = turso.execute("SELECT id FROM brain_nodes WHERE label_key=?", [label_key])
    return rows[0]["id"] if rows else None


def fetch_context(workspace: str, limit: int = CONTEXT_LIMIT) -> str:
    """Nodi rilevanti (workspace corrente prima, poi piu' rinforzati/recenti) + relazioni."""
    _bootstrap()
    nodes = turso.execute(
        "SELECT id, label, summary, workspace, tags FROM brain_nodes "
        "ORDER BY (workspace = ?) DESC, hits DESC, updated_at DESC LIMIT ?",
        [workspace, limit],
    )
    if not nodes:
        return ""

    ids = [n["id"] for n in nodes]
    id_to_label = {n["id"]: n["label"] for n in nodes}
    placeholders = ",".join("?" * len(ids))
    edges = turso.execute(
        f"SELECT source_id, target_id, relation FROM brain_edges "
        f"WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})",
        ids + ids,
    )

    lines = ["## Second brain — nodi noti (memoria a lungo termine)"]
    for n in nodes:
        tag = f" [{n['workspace']}]" if n.get("workspace") else ""
        summary = f" — {n['summary']}" if n.get("summary") else ""
        lines.append(f"- {n['label']}{tag}{summary}")
    if edges:
        lines.append("\nRelazioni:")
        for e in edges:
            src = id_to_label.get(e["source_id"], "?")
            tgt = id_to_label.get(e["target_id"], "?")
            rel = e.get("relation") or "collegato a"
            lines.append(f"- {src} -> {rel} -> {tgt}")
    return "\n".join(lines)


def _store(payload: dict, workspace: str) -> None:
    id_by_key: dict[str, str] = {}

    for node in payload.get("nodes", []) or []:
        label = (node.get("label") or "").strip()
        if not label:
            continue
        label_key = label.lower()
        tags = ",".join(node.get("tags") or [])
        turso.execute(
            "INSERT INTO brain_nodes (id, label, label_key, summary, workspace, tags, hits) "
            "VALUES (?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(label_key) DO UPDATE SET "
            "summary = excluded.summary, tags = excluded.tags, "
            "hits = hits + 1, updated_at = CURRENT_TIMESTAMP",
            [str(uuid.uuid4()), label, label_key, node.get("summary"), node.get("workspace") or workspace, tags],
        )
        node_id = _get_node_id(label_key)
        if node_id:
            id_by_key[label_key] = node_id

    for edge in payload.get("edges", []) or []:
        src_key = (edge.get("source") or "").strip().lower()
        tgt_key = (edge.get("target") or "").strip().lower()
        if not src_key or not tgt_key:
            continue
        src_id = id_by_key.get(src_key) or _get_node_id(src_key)
        tgt_id = id_by_key.get(tgt_key) or _get_node_id(tgt_key)
        if not src_id or not tgt_id:
            continue
        turso.execute(
            "INSERT OR IGNORE INTO brain_edges (id, source_id, target_id, relation) VALUES (?, ?, ?, ?)",
            [str(uuid.uuid4()), src_id, tgt_id, (edge.get("relation") or "").strip()],
        )


def extract_and_store(result_text: str, workspace: str) -> str:
    """Estrae ed elabora ogni blocco ```brain```, ritorna il testo senza quei blocchi."""
    matches = list(BRAIN_BLOCK_RE.finditer(result_text))
    if not matches:
        return result_text

    _bootstrap()
    for m in matches:
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        try:
            _store(payload, workspace)
        except (OSError, RuntimeError):
            pass  # errore Turso non deve far fallire la risposta all'utente

    return BRAIN_BLOCK_RE.sub("", result_text).strip()
