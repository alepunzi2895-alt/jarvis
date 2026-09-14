"""
JARVIS — invio messaggi Telegram all'owner. Condiviso tra bot.py (ha gia'
un loop asyncio, chiama questa funzione su un executor separato per non
bloccarlo) e core/voice/daemon.py (processo separato, sincrono, la
chiama in un thread per non ritardare il prossimo ciclo di ascolto) —
un solo punto che costruisce l'URL/spezza i messaggi lunghi/gestisce gli
errori di rete, invece di duplicarlo in entrambi.

A differenza di bot.py (che richiede TOKEN/OWNER_ID a import time — senza
non ha senso che esista), qui la mancanza e' silenziosa: il daemon vocale
deve continuare a funzionare (parlare) anche se Telegram non e'
configurato, esattamente come gia' fa per Turso.
"""

import os

import requests

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OWNER_ID = os.getenv("TELEGRAM_OWNER_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"

_TIMEOUT = 30
_CHUNK_CHARS = 3900  # sotto il limite di 4096 caratteri di Telegram


def send_to_owner(text: str, parse: str | None = None) -> None:
    if not TOKEN or not OWNER_ID:
        return
    for chunk in [text[i : i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)] or ["(vuoto)"]:
        payload = {"chat_id": OWNER_ID, "text": chunk, "disable_web_page_preview": True}
        if parse:
            payload["parse_mode"] = parse
        try:
            requests.post(f"{API}/sendMessage", json=payload, timeout=_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            print(f"(invio Telegram fallito, ignorato: {e})")
