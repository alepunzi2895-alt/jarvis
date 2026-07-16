"""
JARVIS — meteo attuale, iniettato nel system prompt esattamente come data/ora
(stessa richiesta di Alessandro: rispondere a "che meteo c'e'" come a "che ore
sono", core/claude_bridge.py e core/claude_api.py leggono entrambi da qui).

Nessuna API key: Open-Meteo per previsioni e geocoding, ip-api.com come
fallback di posizione (entrambe gratuite, senza registrazione). Risultato
cacheato (CACHE_SECONDS) per non aggiungere una chiamata di rete ad ogni
singolo messaggio: il meteo non cambia abbastanza in fretta da giustificarlo,
e su questa macchina i blip di rete transitori sono un pattern noto (vedi
memoria [[network-quirks-this-pc]]) — un fallimento viene ricordato solo per
FAILURE_CACHE_SECONDS, cosi' non si aggiunge un timeout ad ogni messaggio
mentre la rete e' giu'.

Priorita' di posizione: JARVIS_WEATHER_LAT/LON (esplicito) > JARVIS_WEATHER_CITY
(geocoded) > IP del PC (ip-api.com — impreciso dietro VPN aziendale, ma un
default ragionevole per un utente che si sposta spesso, coerente col profilo
"camper").
"""

from __future__ import annotations

import os
import time

import requests

CACHE_SECONDS = 1200  # 20 minuti
FAILURE_CACHE_SECONDS = 120  # non ritentare ad ogni messaggio se la rete/API e' giu'
_TIMEOUT = 6  # per chiamata di rete (fino a 2 chiamate in sequenza: geocoding/IP + forecast)

_WMO_DESCRIPTIONS = {
    0: "cielo sereno",
    1: "poco nuvoloso",
    2: "parzialmente nuvoloso",
    3: "nuvoloso",
    45: "nebbia",
    48: "nebbia con brina",
    51: "pioviggine leggera",
    53: "pioviggine",
    55: "pioviggine intensa",
    56: "pioviggine gelata",
    57: "pioviggine gelata intensa",
    61: "pioggia leggera",
    63: "pioggia",
    65: "pioggia intensa",
    66: "pioggia gelata",
    67: "pioggia gelata intensa",
    71: "neve leggera",
    73: "neve",
    75: "neve intensa",
    77: "granelli di neve",
    80: "rovesci leggeri",
    81: "rovesci",
    82: "rovesci intensi",
    85: "rovesci di neve leggeri",
    86: "rovesci di neve intensi",
    95: "temporale",
    96: "temporale con grandine",
    99: "temporale con grandine forte",
}

_cache: dict = {"line": None, "ts": 0.0, "ok": False}


def _describe(code: int) -> str:
    return _WMO_DESCRIPTIONS.get(code, "condizioni non disponibili")


def _resolve_location() -> tuple[float, float, str] | None:
    """Posizione (lat, lon, nome-per-display). None se nulla di configurato e
    la geolocalizzazione IP non risponde."""
    lat, lon = os.getenv("JARVIS_WEATHER_LAT", ""), os.getenv("JARVIS_WEATHER_LON", "")
    if lat and lon:
        return float(lat), float(lon), os.getenv("JARVIS_WEATHER_CITY", "posizione salvata")

    city = os.getenv("JARVIS_WEATHER_CITY", "")
    if city:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        results = r.json().get("results") or []
        if results:
            return results[0]["latitude"], results[0]["longitude"], results[0].get("name", city)

    r = requests.get("http://ip-api.com/json/", timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "success":
        return data["lat"], data["lon"], data.get("city", "posizione attuale")
    return None


def _fetch() -> str | None:
    location = _resolve_location()
    if not location:
        return None
    lat, lon, place = location

    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code,wind_speed_10m"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    current = r.json().get("current") or {}
    temp, code, wind = current.get("temperature_2m"), current.get("weather_code"), current.get("wind_speed_10m")
    if temp is None or code is None:
        return None

    line = f"{temp:.0f}°C, {_describe(int(code))}"
    if wind is not None:
        line += f", vento {wind:.0f} km/h"
    return f"{line} ({place})"


def get_weather_line() -> str | None:
    """Meteo attuale come riga breve, pronta da iniettare nel system prompt.
    Best-effort: None se posizione/rete non disponibili, mai un'eccezione —
    stesso principio del riconoscimento volto (core/voice/face_id.py)."""
    now = time.time()
    ttl = CACHE_SECONDS if _cache["ok"] else FAILURE_CACHE_SECONDS
    if _cache["ts"] and now - _cache["ts"] < ttl:
        return _cache["line"]

    try:
        line = _fetch()
    except (requests.RequestException, ValueError, KeyError):
        line = None

    _cache.update(line=line, ts=now, ok=line is not None)
    return line
