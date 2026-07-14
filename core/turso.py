"""
JARVIS — client HTTP minimale per Turso (protocollo pipeline v2).

Parla direttamente con Turso via HTTP, NON passa dal gateway Vercel: su rete
aziendale (GlobalProtect) le POST verso *.vercel.app vengono resettate, mentre
l'host Turso e' raggiungibile. Nessuna porta aperta in ingresso.

Condiviso da core/web_bridge.py (coda task) e core/brain.py (second brain).
"""

import os
import json
import urllib.request

from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("TURSO_JARVIS_DB_URL", "").replace("libsql://", "https://").rstrip("/")
DB_TOKEN = os.getenv("TURSO_JARVIS_AUTH_TOKEN", "")

ENABLED = bool(DB_URL and DB_TOKEN)


def _wrap_arg(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def _pipeline(statements: list[dict]) -> list[dict]:
    body = json.dumps({"requests": statements + [{"type": "close"}]}).encode()
    req = urllib.request.Request(
        f"{DB_URL}/v2/pipeline",
        data=body,
        headers={"Authorization": f"Bearer {DB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    for r in data.get("results", []):
        if r.get("type") == "error":
            raise RuntimeError(r["error"].get("message", "turso error"))
    return data["results"]


def _rows_to_dicts(result: dict) -> list[dict]:
    cols = [c["name"] for c in result["response"]["result"]["cols"]]
    rows = result["response"]["result"]["rows"]
    return [dict(zip(cols, [cell.get("value") for cell in row])) for row in rows]


def execute(sql: str, args: list | None = None) -> list[dict]:
    """Esegue una statement, ritorna le righe (eventuali) come lista di dict."""
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [_wrap_arg(a) for a in args]
    results = _pipeline([{"type": "execute", "stmt": stmt}])
    return _rows_to_dicts(results[0])


def execute_batch(statements: list[tuple[str, list | None]]) -> None:
    """Esegue piu' statement (senza risultati) in una singola pipeline."""
    reqs = []
    for sql, args in statements:
        stmt = {"sql": sql}
        if args:
            stmt["args"] = [_wrap_arg(a) for a in args]
        reqs.append({"type": "execute", "stmt": stmt})
    _pipeline(reqs)
