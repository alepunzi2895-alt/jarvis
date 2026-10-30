"""Limiti del piano Claude Code (finestra 5 ore e 7 giorni) in percentuale.

Claude Code passa alla status line il JSON di sessione, con `rate_limits` per
gli abbonamenti. `scripts/claude_statusline.py` salva quei valori in
`.claude-limits.json`; qui si leggono per il pannello Limiti di /progetti.
Il dato arriva solo quando una sessione interattiva di Claude Code e' aperta.
"""
from datetime import datetime
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / ".claude-limits.json"
STALE_SEC = 6 * 3600
WINDOWS = (("five_hour", "5h"), ("seven_day", "7g"))


def _when(value) -> str | None:
    """Reset in ISO locale: Claude Code puo' passare epoch in secondi oppure stringa ISO."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec="minutes")
    return value if isinstance(value, str) and value else None


def read(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    try:
        record = json.loads(FILE.read_text(encoding="utf-8"))
        at = float(record["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return dict(available=False, windows={}, note="Limiti non letti: apri una sessione Claude Code interattiva.")
    windows = {}
    for key, label in WINDOWS:
        window = record.get(key) or {}
        percent = window.get("used_percentage")
        windows[label] = dict(percent=float(percent) if isinstance(percent, (int, float)) else None,
                              resets_at=_when(window.get("resets_at")))
    return dict(available=True, at=datetime.fromtimestamp(at).astimezone().isoformat(timespec="minutes"),
                stale=now - at > STALE_SEC, windows=windows, note="")
