"""Costi LLM: modelli, prezzi, registro locale e tetti di spesa.

Unica tabella di modelli e prezzi per bridge, LiveBridge, recap IVECO e ponte
VPS (prima erano tre copie divergenti). Ogni risposta API viene registrata in
`.costs.sqlite3` (escluso da Git) con i token reali dell'usage: e' una stima
dai listini, non la fattura, ma rende misurabile la spesa e permette i tetti.

Tetti (env, USD; 0 = disattivo):
- JARVIS_DAILY_BUDGET_USD: oltre questa spesa giornaliera nessuna nuova chiamata.
- JARVIS_REQUEST_BUDGET_USD: una singola richiesta si ferma tra un giro di
  tool e l'altro quando lo supera.
Il registro non deve mai far fallire una risposta: errori SQLite solo nel log.
"""
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import sqlite3

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# I tetti si leggono all'import: claude_bridge importa questo modulo prima
# del proprio load_dotenv(), quindi il .env va caricato qui.
load_dotenv(ROOT / ".env")
DB = ROOT / ".costs.sqlite3"
LOG = logging.getLogger(__name__)

# Alias usati in .env (JARVIS_TEXT_MODEL / JARVIS_VOICE_MODEL). Un ID completo
# passa invariato: JARVIS_VOICE_MODEL=claude-haiku-4-5 torna al modello precedente.
MODEL_ALIASES = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5", "opus": "claude-opus-5-5"}

# USD per milione di token (input, output), listino Anthropic 2026-10.
# Cache: scrittura 1,25x l'input, lettura 0,1x. Haiku 5.5 costa 5x oltre i
# 100K token di prompt: JARVIS resta molto sotto, non gestito.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
}

# Haiku 5.5 pensa di default (effort medium): per risposte brevi basta low,
# meno token e meno attesa. Haiku 4.5 rifiuta il parametro.
EFFORT = {"claude-haiku-5-5": os.getenv("JARVIS_HAIKU_EFFORT", "low")}


def _usd_env(name, default):
    try:
        return max(float(os.getenv(name, default) or 0), 0.0)
    except ValueError:
        return float(default)


DAILY_BUDGET = _usd_env("JARVIS_DAILY_BUDGET_USD", "1.00")
REQUEST_BUDGET = _usd_env("JARVIS_REQUEST_BUDGET_USD", "0.20")


def resolve(name: str) -> str:
    return MODEL_ALIASES.get(name, name)


def request_options(model: str) -> dict:
    effort = EFFORT.get(model)
    return {"output_config": {"effort": effort}} if effort else {}


def _get(usage, field):
    value = usage.get(field) if isinstance(usage, dict) else getattr(usage, field, None)
    # None quando la cache non e' coinvolta; mai far fallire il registro per un campo strano.
    return value if isinstance(value, (int, float)) else 0


def usd(model: str, usage) -> float:
    in_price, out_price = PRICES.get(model, (0.0, 0.0))
    tokens_in = (_get(usage, "input_tokens")
                 + 1.25 * _get(usage, "cache_creation_input_tokens")
                 + 0.1 * _get(usage, "cache_read_input_tokens"))
    return (tokens_in * in_price + _get(usage, "output_tokens") * out_price) / 1_000_000


def _connect():
    db = sqlite3.connect(DB, timeout=5)
    db.execute("""CREATE TABLE IF NOT EXISTS calls (
        at TEXT NOT NULL, channel TEXT NOT NULL, model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL, cache_write INTEGER NOT NULL, cache_read INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL, usd REAL NOT NULL)""")
    return db


def record(channel: str, model: str, usage, cost: float | None = None) -> float:
    """Registra una risposta API e ne ritorna il costo stimato. `cost` esplicito
    per il CLI `claude -p`, che riporta gia' total_cost_usd."""
    cost = usd(model, usage) if cost is None else cost
    try:
        db = _connect()
        try:
            with db:
                db.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?)", (
                    datetime.now().isoformat(timespec="seconds"), channel, model,
                    _get(usage, "input_tokens"), _get(usage, "cache_creation_input_tokens"),
                    _get(usage, "cache_read_input_tokens"), _get(usage, "output_tokens"), cost))
        finally:
            db.close()
    except sqlite3.Error:
        LOG.warning("Registro costi non scrivibile", exc_info=True)
    return cost


def spent(since: datetime) -> float:
    if not DB.exists():
        return 0.0
    try:
        db = _connect()
        try:
            row = db.execute("SELECT COALESCE(SUM(usd), 0) FROM calls WHERE at >= ?",
                             (since.isoformat(timespec="seconds"),)).fetchone()
        finally:
            db.close()
        return float(row[0])
    except sqlite3.Error:
        LOG.warning("Registro costi non leggibile", exc_info=True)
        return 0.0


def _today_start() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def budget_block() -> str | None:
    """Messaggio da restituire al posto della chiamata se il tetto giornaliero e' superato."""
    if DAILY_BUDGET and spent(_today_start()) >= DAILY_BUDGET:
        return (f"Ho raggiunto il tetto di spesa giornaliero (${DAILY_BUDGET:.2f}). "
                "I comandi rapidi funzionano; per il resto riprova domani o alza JARVIS_DAILY_BUDGET_USD.")
    return None


def summary() -> dict:
    today = _today_start()
    result = {"today": spent(today), "last_7_days": spent(today - timedelta(days=6)),
              "last_30_days": spent(today - timedelta(days=29)),
              "daily_budget": DAILY_BUDGET, "request_budget": REQUEST_BUDGET, "by_model": []}
    if DB.exists():
        try:
            db = _connect()
            try:
                rows = db.execute("""SELECT model, channel, COUNT(*), SUM(usd) FROM calls WHERE at >= ?
                    GROUP BY model, channel ORDER BY SUM(usd) DESC""",
                                  ((today - timedelta(days=29)).isoformat(timespec="seconds"),)).fetchall()
            finally:
                db.close()
            result["by_model"] = [dict(model=m, channel=c, calls=n, usd=round(u, 4)) for m, c, n, u in rows]
        except sqlite3.Error:
            LOG.warning("Registro costi non leggibile", exc_info=True)
    return result


def format_summary(data: dict | None = None) -> str:
    data = data or summary()
    if not data["by_model"] and not data["today"]:
        return "Nessuna spesa registrata negli ultimi 30 giorni su questa macchina."
    lines = [f"Spesa LLM stimata: oggi ${data['today']:.3f}, 7 giorni ${data['last_7_days']:.2f}, "
             f"30 giorni ${data['last_30_days']:.2f}."]
    if data["daily_budget"]:
        lines.append(f"Tetto giornaliero ${data['daily_budget']:.2f}.")
    top = data["by_model"][:3]
    if top:
        lines.append("Voci principali (30 giorni): " + "; ".join(
            f"{r['model']} {r['channel']} {r['calls']} chiamate ${r['usd']:.2f}" for r in top) + ".")
    return " ".join(lines)
