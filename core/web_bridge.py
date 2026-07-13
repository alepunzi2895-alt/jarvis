"""
JARVIS — poller per la coda task della web dashboard (Vercel + Turso).
Nessuna porta aperta: il bridge fa solo richieste outbound, come per Telegram.
"""

import os
import asyncio

import requests
from dotenv import load_dotenv

from core.claude_bridge import run_claude

load_dotenv()

WEB_URL = os.getenv("JARVIS_WEB_URL", "").rstrip("/")
SECRET = os.getenv("JARVIS_BOT_SECRET", "")
POLL_SEC = float(os.getenv("JARVIS_WEB_POLL_SEC", "3"))

ENABLED = bool(WEB_URL and SECRET)


def _api(payload: dict) -> dict:
    r = requests.post(f"{WEB_URL}/api/jarvis", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


async def poll_web_queue() -> None:
    print(f"web bridge attivo -> {WEB_URL}")
    while True:
        try:
            task = _api({"action": "task_get", "secret": SECRET}).get("task")
        except Exception as e:  # noqa: BLE001
            print("web poll error:", e)
            await asyncio.sleep(POLL_SEC)
            continue

        if not task:
            await asyncio.sleep(POLL_SEC)
            continue

        print(f"> [web] {task['prompt'][:80]}")
        try:
            result, sid, cost = await run_claude(task["prompt"], ws=task.get("workspace"))
            _api(
                {
                    "action": "task_result_push",
                    "secret": SECRET,
                    "task_id": task["id"],
                    "status": "done",
                    "result": result,
                    "session_id": sid,
                    "cost_usd": cost,
                }
            )
        except Exception as e:  # noqa: BLE001
            try:
                _api(
                    {
                        "action": "task_result_push",
                        "secret": SECRET,
                        "task_id": task["id"],
                        "status": "error",
                        "result": str(e)[:1500],
                    }
                )
            except Exception as e2:  # noqa: BLE001
                print("web result push error:", e2)
