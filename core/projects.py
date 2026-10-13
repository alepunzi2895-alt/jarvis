"""Catalogo locale: scoperta leggera, senza concedere permessi di scrittura."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".project-catalog.json"
NOTES = ROOT / "memory" / "projects"
# Compatibilita' con memoria e comandi esistenti, non elenco dei progetti.
ALIASES = {
    "tradepilot-ai": ("tradepilot", "trade pilot"),
    "aura": ("auraibiza", "aura-ibiza", "aura ibiza"),
    "whitesoul": ("whitesoulibiza", "white soul", "white-soul"),
    "trading": ("tradeflow-ai", "tradeflow", "tradeflow ai"),
    "isabela": ("ai-persona-isabela",),
    "vino": ("vinitalimport",),
    "iveco": ("databricks", "qlik", "unity catalog", "pyspark", "genie", "dbsql"),
}


def slug(value):
    return re.sub(r"[^\w]+", "-", value.casefold()).strip("-").replace("_", "-")


def canonical(value):
    key = slug(value)
    return next((k for k, names in ALIASES.items() if key == k or key in map(slug, names)), key)


@dataclass
class Project:
    key: str
    label: str
    path: str | None = None
    notes_file: str = ""
    source: str = "memoria"

    @property
    def env_var(self):
        return "WS_" + self.key.upper().replace("-", "_")


def catalog():
    entries = {}
    def add(name, path=None, note="", source="memoria", label=None):
        key = canonical(name)
        old = entries.get(key)
        entries[key] = Project(key, label or (old.label if old else name),
                               str(path) if path else (old.path if old else None),
                               note or (old.notes_file if old else ""), source)
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        config = {}
    for note in sorted(NOTES.glob("*.md")):
        if note.stem == "altri-progetti":  # nota collettiva, non un progetto
            continue
        try:
            with note.open(encoding="utf-8") as stream:
                title = stream.readline().strip().lstrip("# ")
        except (OSError, UnicodeError):
            continue
        add(note.stem, note=note.name, label=title or note.stem)
    roots = config.get("roots", [str(ROOT.parent)])
    for raw in roots:
        root = Path(raw).resolve()
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                # Non seguire junction/symlink verso altri dischi o cartelle.
                if child.resolve().parent != root or not (child / ".git").exists():
                    continue
                add(child.name, child.resolve(), source="cartella Git")
            except OSError:
                continue
    for item in config.get("projects", []):
        add(item["name"], item.get("path"), source="registro locale")
    for name, value in sorted(os.environ.items()):
        if name.startswith("WS_") and value.strip():
            add(name[3:].lower(), Path(value).resolve(), source=name)
    add("jarvis", ROOT, source="JARVIS")
    return sorted(entries.values(), key=lambda p: p.label.casefold())


def find(key):
    key = canonical(key)
    return next((p for p in catalog() if p.key == key), None)


def detect(prompt, previous="jarvis"):
    normalized = slug(re.sub(r"^\s*jarvis[, :]+", "", prompt, flags=re.I))
    matches = []
    for p in catalog():
        names = {p.key, p.label, *ALIASES.get(p.key, ())}
        if p.path:
            names.add(Path(p.path).name)
        if any(re.search(r"(?<![\w])" + re.escape(slug(n)) + r"(?![\w])", normalized) for n in names if n):
            matches.append(p.key)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1 or re.search(r"\b(tutti|progetti|panoramica|giornata|settimana)\b", prompt.casefold()):
        return "jarvis"
    return previous if find(previous) else "jarvis"


def context():
    rows = [f"{p.key}: {p.label} ({'cartella locale' if p.path else 'solo memoria/registro'})" for p in catalog()]
    return "Catalogo progetti aggiornato (metadati, non contenuti verificati):\n" + "\n".join(rows)


def read_context(key):
    p = find(key)
    if not p:
        raise ValueError("Progetto sconosciuto: usa list_projects.")
    result = asdict(p)
    if p.notes_file:
        note = NOTES / p.notes_file
        result["notes"] = note.read_text(encoding="utf-8")[-16000:]
        result["notes_modified"] = datetime.fromtimestamp(note.stat().st_mtime).isoformat()
    result["notice"] = "Le note sono memoria storica, non una verifica dello stato attuale."
    return result


def git_read(path, *args):
    """Solo comandi fissati dal codice, nessun argv costruito dal modello."""
    if args not in (("status", "--short", "--branch"), ("log", "-1", "--format=%h %s (%cr)")):
        raise ValueError("Comando git non ammesso")
    return subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(path), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


class Workspaces(Mapping):
    def __getitem__(self, key):
        project = find(key)
        if not project or not project.path:
            raise KeyError(key)
        return project.path

    def __iter__(self):
        return iter(p.key for p in catalog() if p.path)

    def __len__(self):
        return sum(bool(p.path) for p in catalog())
