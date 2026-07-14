"""
JARVIS — poller per la coda task della web dashboard.

Parla direttamente con Turso via HTTP (core/turso.py), NON passa dal gateway
Vercel: su questa rete (GlobalProtect aziendale) le richieste POST verso
*.vercel.app vengono resettate, mentre l'host Turso e' raggiungibile.
Nessuna porta aperta in ingresso: solo richieste outbound, come per Telegram.
"""

import os
import asyncio

from core import turso
from core.claude_bridge import run_claude

POLL_SEC = float(os.getenv("JARVIS_WEB_POLL_SEC", "3"))

ENABLED = turso.ENABLED


async def _claim_next_task() -> dict | None:
    def work():
        rows = turso.execute(
            "SELECT id, channel, workspace, prompt, image_b64 FROM tasks "
            "WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
        )
        if not rows:
            return None
        task = rows[0]
        turso.execute(
            "UPDATE tasks SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [task["id"]],
        )
        return task

    return await asyncio.to_thread(work)


async def _push_result(task_id: str, status: str, result: str, session_id: str | None, cost_usd: float) -> None:
    def work():
        turso.execute(
            "UPDATE tasks SET status=?, result=?, session_id=?, cost_usd=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [status, result, session_id, cost_usd, task_id],
        )

    await asyncio.to_thread(work)


async def poll_web_queue() -> None:
    print(f"web bridge attivo -> Turso {turso.DB_URL}")
    while True:
        try:
            task = await _claim_next_task()
        except (OSError, RuntimeError) as e:
            print("web poll error:", e)
            await asyncio.sleep(POLL_SEC)
            continue

        if not task:
            await asyncio.sleep(POLL_SEC)
            continue

        print(f"> [web] {task['prompt'][:80]}")
        try:
            result, sid, cost = await run_claude(
                task["prompt"],
                ws=task.get("workspace"),
                image_b64=task.get("image_b64"),
                channel=task.get("channel") or "text",
            )
            await _push_result(task["id"], "done", result, sid, cost)
        except Exception as e:  # noqa: BLE001
            try:
                await _push_result(task["id"], "error", str(e)[:1500], None, 0.0)
            except Exception as e2:  # noqa: BLE001
                print("web result push error:", e2)
