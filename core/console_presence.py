"""Console della dashboard aperta sul PC: segnale fra LiveBridge e daemon vocale.

LiveBridge (core/live_server.py) scrive quante console desktop sono collegate
via WebSocket; il daemon vocale apre il microfono per la wake word solo
quando ce n'e' almeno una (richiesta di Alessandro, 2026-10-15: niente
ascolto passivo a console chiusa). Il file viene riscritto ogni
HEARTBEAT_SEC: se LiveBridge muore senza azzerarlo, dopo STALE_SEC vale
come console chiusa.
"""
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / ".console-presence.json"
HEARTBEAT_SEC = 10
STALE_SEC = 30
CACHE_SEC = 1.0

_cache = {"at": 0.0, "value": False}


def write(clients: int, mic_enabled: int = 0) -> None:
    tmp = PATH.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps({"clients": clients, "mic_enabled": mic_enabled, "ts": time.time()}), encoding="utf-8")
        os.replace(tmp, PATH)
    except OSError:
        # Su Windows os.replace fallisce se il daemon ha il file aperto in
        # quell'istante: il prossimo heartbeat riprova.
        pass


def read_open() -> bool:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return int(data.get("clients", 0)) > 0 and time.time() - float(data.get("ts", 0)) < STALE_SEC
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def is_open() -> bool:
    """Come read_open(), con cache di CACHE_SEC: il loop della wake word lo
    chiama ogni 100 ms."""
    now = time.monotonic()
    if now - _cache["at"] >= CACHE_SEC:
        _cache.update(at=now, value=read_open())
    return _cache["value"]


def is_mic_enabled() -> bool:
    """True solo se una dashboard desktop ha attivato esplicitamente il mic."""
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        fresh = time.time() - float(data.get("ts", 0)) < STALE_SEC
        return fresh and int(data.get("mic_enabled", 0)) > 0
    except (OSError, ValueError, TypeError, AttributeError):
        return False
