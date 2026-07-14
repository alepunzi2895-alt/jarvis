"""
JARVIS — ObsidianVault: legge/scrive direttamente sui file .md del vault,
nessun plugin richiesto (Obsidian e' solo un editor sopra una cartella di
file di testo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_/-]+)")


class ObsidianVault:
    def __init__(self, vault_path: str | Path):
        self.root = Path(vault_path)
        if not self.root.is_dir():
            raise FileNotFoundError(f"Vault non trovato: {self.root}")

    def _resolve(self, rel_path: str | Path) -> Path:
        rel = str(rel_path)
        if not rel.lower().endswith(".md"):
            rel += ".md"
        return self.root / rel

    def read_note(self, path: str | Path) -> str:
        p = self._resolve(path)
        if not p.is_file():
            raise FileNotFoundError(f"Nota non trovata: {path}")
        return p.read_text(encoding="utf-8")

    def write_note(self, path: str | Path, content: str, mode: str = "append") -> Path:
        if mode not in ("append", "overwrite"):
            raise ValueError("mode deve essere 'append' o 'overwrite'")
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append" and p.is_file():
            existing = p.read_text(encoding="utf-8")
            sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
            p.write_text(existing + sep + content.rstrip("\n") + "\n", encoding="utf-8")
        else:
            p.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
        return p

    def create_daily_note(self, for_date: date | None = None) -> Path:
        d = for_date or date.today()
        p = self._resolve(f"Daily/{d.isoformat()}")
        if not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {d.isoformat()}\n\n", encoding="utf-8")
        return p

    def search(self, query: str) -> list[Path]:
        needle = query.lower()
        hits = []
        for md in self._all_notes():
            text = self._safe_read(md)
            if text is None:
                continue
            if needle in text.lower() or needle in md.stem.lower():
                hits.append(md.relative_to(self.root))
        return hits

    def link(self, a: str | Path, b: str | Path) -> Path:
        target_name = Path(b).stem
        return self.write_note(a, f"[[{target_name}]]", mode="append")

    def get_frontmatter(self, path: str | Path) -> dict:
        text = self.read_note(path)
        m = FRONTMATTER_RE.match(text)
        if not m:
            return {}
        return yaml.safe_load(m.group(1)) or {}

    def set_frontmatter(self, path: str | Path, data: dict) -> Path:
        p = self._resolve(path)
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        body = FRONTMATTER_RE.sub("", text, count=1)
        block = "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(block + body, encoding="utf-8")
        return p

    def list_tags(self) -> set[str]:
        tags: set[str] = set()
        for md in self._all_notes():
            text = self._safe_read(md)
            if text is None:
                continue
            tags.update(self._tags_of_text(text))
        return tags

    def notes_by_tag(self, tag: str) -> list[Path]:
        tag = tag.lstrip("#")
        hits = []
        for md in self._all_notes():
            text = self._safe_read(md)
            if text is None:
                continue
            if tag in self._tags_of_text(text):
                hits.append(md.relative_to(self.root))
        return hits

    def _tags_of_text(self, text: str) -> set[str]:
        m = FRONTMATTER_RE.match(text)
        body = FRONTMATTER_RE.sub("", text, count=1)
        found = set(TAG_RE.findall(body))
        if m:
            data = yaml.safe_load(m.group(1)) or {}
            raw = data.get("tags")
            if isinstance(raw, list):
                found.update(str(t) for t in raw)
            elif isinstance(raw, str):
                found.add(raw)
        return found

    def _all_notes(self):
        for md in self.root.rglob("*.md"):
            if ".obsidian" in md.parts:
                continue
            yield md

    @staticmethod
    def _safe_read(md: Path) -> str | None:
        try:
            return md.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None


@dataclass
class VaultChange:
    path: Path
    kind: str  # "created" | "modified" | "deleted"


class VaultWatcher:
    """Notifica (callback) sulle modifiche esterne ai file .md del vault."""

    def __init__(self, vault: ObsidianVault, on_change):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        self._on_change = on_change
        self._observer = Observer()

        outer = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                outer._dispatch(event, "created")

            def on_modified(self, event):
                outer._dispatch(event, "modified")

            def on_deleted(self, event):
                outer._dispatch(event, "deleted")

        self._observer.schedule(_Handler(), str(vault.root), recursive=True)

    def _dispatch(self, event, kind: str) -> None:
        if event.is_directory or not str(event.src_path).lower().endswith(".md"):
            return
        self._on_change(VaultChange(path=Path(event.src_path), kind=kind))

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
