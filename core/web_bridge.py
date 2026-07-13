"""
JARVIS — poller per la coda task della web dashboard.

Parla direttamente con Turso via HTTP (stesso meccanismo usato da web/api/jarvis.js),
NON passa dal gateway Vercel: su questa rete (GlobalProtect aziendale) le richieste
POST verso *.vercel.app vengono resettate, mentre l'host Turso e' raggiungibile.
Nessuna porta aperta in ingresso: solo richieste outbound, come per Telegram.
"""

import os
import json
import asyncio
import urllib.request
import urllib.error

from dotenv import load_dotenv

from core.claude_bridge import run_claude

load_dotenv()

DB_URL = os.getenv("TURSO_JARVIS_DB_URL", "").replace("libsql://", "https://").rstrip("/")
DB_TOKEN = os.getenv("TURSO_JARVIS_AUTH_TOKEN", "")
POLL_SEC = float(os.getenv("JARVIS_WEB_POLL_SEC", "3"))

ENABLED = bool(DB_URL and DB_TOKEN)


def _turso(statements: list[dict]) -> list[dict]:
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


def _row_to_dict(result: dict) -> dict | None:
    cols = [c["name"] for c in result["response"]["result"]["cols"]]
    rows = result["response"]["result"]["rows"]
    if not rows:
        return None
    values = [cell.get("value") for cell in rows[0]]
    return dict(zip(cols, values))


async def _claim_next_task() -> dict | None:
    def work():
        results = _turso(
            [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": "SELECT id, workspace, prompt FROM tasks "
                        "WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
                    },
                }
            ]
        )
        task = _row_to_dict(results[0])
        if not task:
            return None
        _turso(
            [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": "UPDATE tasks SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        "args": [{"type": "text", "value": task["id"]}],
                    },
                }
            ]
        )
        return task

    return await asyncio.to_thread(work)


async def _push_result(task_id: str, status: str, result: str, session_id: str | None, cost_usd: float) -> None:
    def work():
        _turso(
            [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": "UPDATE tasks SET status=?, result=?, session_id=?, cost_usd=?, "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        "args": [
                            {"type": "text", "value": status},
                            {"type": "text", "value": result},
                            {"type": "text", "value": session_id} if session_id else {"type": "null"},
                            {"type": "float", "value": cost_usd},
                            {"type": "text", "value": task_id},
                        ],
                    },
                }
            ]
        )

    await asyncio.to_thread(work)


async def poll_web_queue() -> None:
    print(f"web bridge attivo -> Turso {DB_URL}")
    while True:
        try:
            task = await _claim_next_task()
        except (urllib.error.URLError, RuntimeError) as e:
            print("web poll error:", e)
            await asyncio.sleep(POLL_SEC)
            continue

        if not task:
            await asyncio.sleep(POLL_SEC)
            continue

        print(f"> [web] {task['prompt'][:80]}")
        try:
            result, sid, cost = await run_claude(task["prompt"], ws=task.get("workspace"))
            await _push_result(task["id"], "done", result, sid, cost)
        except Exception as e:  # noqa: BLE001
            try:
                await _push_result(task["id"], "error", str(e)[:1500], None, 0.0)
            except Exception as e2:  # noqa: BLE001
                print("web result push error:", e2)
