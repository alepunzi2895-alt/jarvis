"""Status line di Claude Code: salva i limiti del piano per il pannello Limiti di JARVIS.

Claude Code passa su stdin il JSON di sessione. Se contiene `rate_limits` (abbonamento),
i valori 5 ore e 7 giorni vanno in `.claude-limits.json` nella cartella JARVIS; poi
stampa una riga breve. Senza `rate_limits` non scrive nulla, cosi' il dato buono resta.
"""
import json
from pathlib import Path
import sys
import time

TARGET = Path(__file__).resolve().parents[1] / ".claude-limits.json"


def save(data: dict, target: Path = TARGET, now: float | None = None) -> str:
    limits = data.get("rate_limits") or {}
    if not limits:
        return ""
    record = dict(at=time.time() if now is None else now,
                  five_hour=limits.get("five_hour"), seven_day=limits.get("seven_day"))
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record), encoding="utf-8")
    temporary.replace(target)
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7g")):
        percent = (record[key] or {}).get("used_percentage")
        if isinstance(percent, (int, float)):
            parts.append(f"{label} {percent:.0f}%")
    return " · ".join(parts)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        line = save(json.load(sys.stdin))
    except ValueError:
        line = ""
    print(line)
