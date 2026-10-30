"""Snapshot del desktop verso la VPS (core/gateway.py), ogni ~30 s.

La VPS lo mostra quando il PC e' spento. Stesso ponte e stesso token dei
messaggi Telegram: JARVIS_TELEGRAM_RELAY_URL e JARVIS_RELAY_TOKEN.
Errori di rete: nessun effetto sul PC, si riprova al giro successivo.
"""
import asyncio
import logging
import os
import ssl
import time

import certifi
from aiohttp import ClientSession, ClientTimeout, TCPConnector

from core import feed, servicenow

LOG = logging.getLogger(__name__)
PUSH_EVERY_SEC = 30
FEED_ITEMS = 40


def relay_base():
    url = os.getenv("JARVIS_TELEGRAM_RELAY_URL", "").rstrip("/")
    return url.removesuffix("/telegram/updates").rstrip("/") if url else ""


def build_snapshot(items, incidents=None):
    snapshot = {"pc_time": time.strftime("%Y-%m-%d %H:%M:%S"), "feed": items}
    if incidents:
        snapshot["iveco_incidents"] = incidents
    return snapshot


async def push_once(session, base, token):
    items = await asyncio.to_thread(feed.recent, "", FEED_ITEMS)
    incidents = await asyncio.to_thread(servicenow.cached_incidents)
    async with session.post(f"{base}/pc/snapshot", json=build_snapshot(items, incidents),
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=ClientTimeout(total=20)) as response:
        await response.read()
        return response.status


async def push_forever():
    base = relay_base()
    token = os.getenv("JARVIS_RELAY_TOKEN", "")
    if not base or not token:
        return
    connector = TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))
    async with ClientSession(connector=connector) as session:
        while True:
            try:
                status = await push_once(session, base, token)
                if status != 200:
                    LOG.warning("Snapshot alla VPS rifiutato: HTTP %s", status)
            except Exception as error:  # noqa: BLE001 — rete o VPS giu': riprova al giro dopo
                LOG.info("Snapshot alla VPS non inviato: %s", type(error).__name__)
            await asyncio.sleep(PUSH_EVERY_SEC)
