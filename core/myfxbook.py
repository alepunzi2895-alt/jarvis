"""
JARVIS — snapshot P&L reale del trading (TradeFlow/XAU, account Myfxbook
verificato "MFKK") via l'API ufficiale Myfxbook (www.myfxbook.com/api).

Sola lettura: nessuna funzione qui esegue un ordine reale — vietato da
CLAUDE.md ("mai eseguire ordini di trading reali, solo analisi/backtest/
report"), qui semplicemente non esiste nessuna chiamata che lo permetta.

Richiede MYFXBOOK_EMAIL/MYFXBOOK_PASSWORD in .env (le stesse credenziali
del login su myfxbook.com) — degrada a ENABLED=False senza, stesso
principio gia' in uso nel resto del repo (turso.ENABLED, Genie space_id,
ecc.): il resto del codice controlla ENABLED prima di chiamare, non deve
gestire un'eccezione di configurazione ad ogni chiamata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

BASE = "https://www.myfxbook.com/api"
EMAIL = os.getenv("MYFXBOOK_EMAIL", "")
PASSWORD = os.getenv("MYFXBOOK_PASSWORD", "")
ENABLED = bool(EMAIL and PASSWORD)

_TIMEOUT = 10


class MyfxbookError(Exception):
    pass


@dataclass
class AccountSnapshot:
    name: str
    balance: float
    equity: float
    gain: float
    drawdown: float
    profit: float
    won_trades: int
    lost_trades: int


def _get(path: str) -> dict:
    r = requests.get(f"{BASE}{path}", timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    # Myfxbook usa sia il booleano true sia la stringa "true" per "error" a
    # seconda dell'endpoint — stesso comportamento gia' documentato dal
    # proxy Node.js di tradeflow-ai (api/myfxbook.js), qui replicato.
    if data.get("error") in (True, "true"):
        raise MyfxbookError(data.get("message") or "Errore Myfxbook")
    return data


def _login() -> str:
    if not ENABLED:
        raise MyfxbookError("Myfxbook non configurato (MYFXBOOK_EMAIL/MYFXBOOK_PASSWORD mancanti nel .env).")
    data = _get(f"/login.json?email={EMAIL}&password={PASSWORD}")
    session = data.get("session")
    if not session:
        raise MyfxbookError("Login Myfxbook fallito — verifica email/password.")
    return session


def _logout(session: str) -> None:
    try:
        requests.get(f"{BASE}/logout.json?session={session}", timeout=_TIMEOUT)
    except Exception:  # noqa: BLE001 — un logout fallito non e' un problema per chi chiama
        pass


def get_accounts_sync() -> list[AccountSnapshot]:
    """Login + lettura account + logout in un solo giro — nessuna sessione
    tenuta in vita tra una chiamata e l'altra (uso sporadico, poche volte al
    giorno: non vale la complessita' di una cache di sessione con scadenza)."""
    session = _login()
    try:
        data = _get(f"/get-my-accounts.json?session={session}")
        accounts = data.get("accounts") or []
        return [
            AccountSnapshot(
                name=a.get("name") or "Account",
                balance=float(a.get("balance") or 0),
                equity=float(a.get("equity") or 0),
                gain=float(a.get("gain") or 0),
                drawdown=float(a.get("drawdown") or 0),
                profit=float(a.get("profit") or 0),
                won_trades=int(a.get("wonTrades") or 0),
                lost_trades=int(a.get("lostTrades") or 0),
            )
            for a in accounts
        ]
    finally:
        _logout(session)


def format_accounts(accounts: list[AccountSnapshot], voice: bool) -> str:
    if not accounts:
        return "Nessun account Myfxbook trovato, Signore." if voice else "Nessun account Myfxbook trovato."

    if voice:
        parts = [
            f"{a.name}: equity {a.equity:.0f}, guadagno {a.gain:.1f} percento, drawdown {a.drawdown:.1f} percento"
            for a in accounts
        ]
        return f"{'; '.join(parts)}, Signore."

    lines = ["Trading (Myfxbook):", ""]
    for a in accounts:
        total = a.won_trades + a.lost_trades
        winrate = f"{(a.won_trades / total * 100):.0f}%" if total else "n/d"
        lines.append(
            f"**{a.name}** — Equity {a.equity:.2f} · Gain {a.gain:.2f}% · "
            f"Drawdown {a.drawdown:.2f}% · Profit {a.profit:.2f} · Winrate {winrate} ({total} trade)"
        )
    return "\n".join(lines).strip()
