"""Messaggi comuni a Telegram e chat della piattaforma (LiveBridge).

Ogni processo (bot.py, daemon vocale, LiveBridge, lavori Claude Code) scrive
qui quello che manda a Telegram e quello che arriva da Telegram; il LiveBridge
legge il file e lo mostra nella chat della dashboard. File locale e non
versionato: contiene conversazioni.
"""
from html import unescape
import json
from pathlib import Path
import re
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / ".jarvis-feed.jsonl"
_KEEP = 300
_MAX_CHARS = 4000
_lock = threading.Lock()
_last_id = 0


def plain(text: str, parse: str | None = None) -> str:
    """Testo leggibile in dashboard: i messaggi Telegram in HTML perdono i tag."""
    if parse and parse.upper() == "HTML":
        text = unescape(re.sub(r"<[^>]+>", "", text))
    return text.strip()[:_MAX_CHARS]


def add(source: str, text: str = "", prompt: str = "", parse: str | None = None) -> None:
    """`source`: telegram (risposte e avvisi), telegram_in (scritto da Alessandro), voce.
    Mai un errore verso il chiamante: la chat della piattaforma e' un di piu'."""
    global _last_id
    with _lock:
        # Su Windows time_ns() avanza a scatti di ~1 ms: due messaggi di fila
        # avrebbero lo stesso id e `recent(after)` perderebbe il secondo.
        _last_id = max(time.time_ns(), _last_id + 1)
        new_id = _last_id
    item = dict(id=str(new_id), at=time.strftime("%Y-%m-%d %H:%M:%S"), source=source,
                prompt=plain(prompt), text=plain(text, parse))
    if not item["prompt"] and not item["text"]:
        return
    try:
        with _lock:
            with FEED.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            if FEED.stat().st_size > 1_500_000:
                lines = FEED.read_text(encoding="utf-8").splitlines()[-_KEEP:]
                temporary = FEED.with_suffix(".tmp")
                temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
                temporary.replace(FEED)
    except OSError:
        pass


def recent(after: str = "", limit: int = 50) -> list[dict]:
    """Ultimi messaggi, dal piu' vecchio; con `after` solo quelli successivi a quell'id."""
    try:
        lines = FEED.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    items = []
    for line in lines[-_KEEP:]:
        try:
            item = json.loads(line)
        except ValueError:
            continue  # riga scritta a meta' da un altro processo
        if not after or int(item["id"]) > int(after):
            items.append(item)
    return items[-limit:]
