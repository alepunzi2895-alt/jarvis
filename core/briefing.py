"""
JARVIS — briefing mattutino unificato: meteo + calendario di oggi + mail
non lette + P&L trading (se configurato) + stato progetti in un'unica
risposta, invece di quattro/cinque pezzi da chiedere uno per uno —
richiesta esplicita di Alessandro (2026-09-16).

Ogni sezione e' opzionale e degrada in silenzio (stesso principio del
second brain, core/brain.py::fetch_context): un Outlook irraggiungibile o
un blip meteo non devono mai far fallire l'intero briefing. I dati si
raccolgono UNA volta sola (gather_briefing_data, bloccante — va lanciata
con asyncio.to_thread da chi chiama) e si formattano testo/voce a parte,
per non raddoppiare le chiamate di rete quando serve entrambe le versioni
(es. /buongiorno su Telegram: risposta scritta + parlata).
"""

from __future__ import annotations

import datetime as dt

from core import myfxbook, outlook, project_status, weather


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — una sezione che fallisce non deve rompere le altre
        return None


def _minutes_until_midnight(now: dt.datetime) -> int:
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return max(1, int((end_of_day - now).total_seconds() / 60))


def gather_briefing_data(executor) -> dict:
    now = dt.datetime.now()
    data = {
        "now": now,
        "weather": _safe(weather.get_weather_line),
        "events": _safe(lambda: outlook.get_upcoming_events_sync(minutes_ahead=_minutes_until_midnight(now))),
        "unread": _safe(outlook.count_unread_emails_sync),
        "statuses": _safe(lambda: project_status.check_all(executor)),
    }
    if myfxbook.ENABLED:
        data["trading"] = _safe(myfxbook.get_accounts_sync)
    return data


_GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
_MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
         "agosto", "settembre", "ottobre", "novembre", "dicembre")


def format_briefing(data: dict, voice: bool) -> str:
    # Prima l'ora, poi la data (2026-10-16: "Sono le 16/10 11:59" suonava al contrario).
    now = data["now"]
    if voice:
        day = f"{_GIORNI[now.weekday()]} {now.day} {_MESI[now.month - 1]}"
        parts = [f"Buongiorno, Signore. Sono le {now:%H:%M} di {day}."]
    else:
        parts = [f"Buongiorno — {now:%H:%M} · {now:%d/%m}"]

    if data.get("weather"):
        parts.append(data["weather"] if voice else f"Meteo: {data['weather']}")

    events = data.get("events")
    if events is not None:
        parts.append(outlook.format_events(events, voice=voice))

    unread = data.get("unread")
    if unread is not None:
        parts.append(outlook.format_unread_count(unread, voice=voice))

    trading = data.get("trading")
    if trading is not None:
        parts.append(myfxbook.format_accounts(trading, voice=voice))

    statuses = data.get("statuses")
    if statuses is not None:
        parts.append(project_status.format_report(statuses, voice=voice))

    return " ".join(parts) if voice else "\n\n".join(parts)


def build_briefing_text(executor) -> str:
    return format_briefing(gather_briefing_data(executor), voice=False)


def build_briefing_voice(executor) -> str:
    return format_briefing(gather_briefing_data(executor), voice=True)
