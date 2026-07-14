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
import os
import re
import uuid
from pathlib import Path

from core import turso
from core.obsidian import ObsidianVault

BRAIN_BLOCK_RE = re.compile(r"```brain\s*\n(.*?)\n```", re.DOTALL)
SLUG_RE = re.compile(r"[^a-z0-9]+")

CONTEXT_LIMIT = 40

_bootstrapped = False
_vault_checked = False
_vault_instance: ObsidianVault | None = None


def _slug(label: str) -> str:
    return SLUG_RE.sub("-", label.strip().lower()).strip("-") or "nodo"


def _vault() -> ObsidianVault | None:
    """Vault Obsidian per il mirror delle note (opzionale, degrada senza errori)."""
    global _vault_checked, _vault_instance
    if not _vault_checked:
        _vault_checked = True
        path = os.getenv("JARVIS_VAULT_PATH", "")
        if path and Path(path).is_dir():
            _vault_instance = ObsidianVault(path)
    return _vault_instance


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


def _mirror_node_to_vault(vault: ObsidianVault, label: str, summary: str | None, workspace: str, tags: list) -> None:
    note_path = f"SecondBrain/{_slug(label)}"
    is_new = False
    try:
        vault.read_note(note_path)
    except FileNotFoundError:
        is_new = True

    if is_new:
        body = f"# {label}\n"
        if summary:
            body += f"\n{summary}\n"
        try:
            vault.write_note(note_path, body, mode="overwrite")
        except OSError:
            return

    try:
        fm = vault.get_frontmatter(note_path)
    except (OSError, FileNotFoundError):
        fm = {}
    fm["workspace"] = workspace
    fm["tags"] = sorted(set(fm.get("tags") or []) | set(tags))
    fm["hits"] = int(fm.get("hits") or 0) + 1
    fm["source"] = "second-brain"
    try:
        vault.set_frontmatter(note_path, fm)
    except OSError:
        pass


def _mirror_edge_to_vault(vault: ObsidianVault, src_label: str, tgt_label: str) -> None:
    src_path = f"SecondBrain/{_slug(src_label)}"
    tgt_path = f"SecondBrain/{_slug(tgt_label)}"
    try:
        existing = vault.read_note(src_path)
    except FileNotFoundError:
        return
    if f"[[{_slug(tgt_label)}]]" in existing:
        return  # gia' collegato, non duplicare il wikilink
    try:
        vault.link(src_path, tgt_path)
    except OSError:
        pass


def _store(payload: dict, workspace: str) -> None:
    id_by_key: dict[str, str] = {}
    vault = _vault()

    for node in payload.get("nodes", []) or []:
        label = (node.get("label") or "").strip()
        if not label:
            continue
        label_key = label.lower()
        tags = node.get("tags") or []
        turso.execute(
            "INSERT INTO brain_nodes (id, label, label_key, summary, workspace, tags, hits) "
            "VALUES (?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(label_key) DO UPDATE SET "
            "summary = excluded.summary, tags = excluded.tags, "
            "hits = hits + 1, updated_at = CURRENT_TIMESTAMP",
            [str(uuid.uuid4()), label, label_key, node.get("summary"), node.get("workspace") or workspace, ",".join(tags)],
        )
        node_id = _get_node_id(label_key)
        if node_id:
            id_by_key[label_key] = node_id
        if vault:
            _mirror_node_to_vault(vault, label, node.get("summary"), node.get("workspace") or workspace, tags)

    for edge in payload.get("edges", []) or []:
        src_label = (edge.get("source") or "").strip()
        tgt_label = (edge.get("target") or "").strip()
        src_key, tgt_key = src_label.lower(), tgt_label.lower()
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
        if vault:
            _mirror_edge_to_vault(vault, src_label, tgt_label)


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
