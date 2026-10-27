"""Outlook Web: piano B in sola lettura quando Outlook desktop (COM) non risponde.

Richiesta di Alessandro, 2026-10-27: "se Outlook non risponde leggilo da
quello web". Legge mail, conteggio non lette e agenda dal browser JARVIS
(profilo Playwright con la sessione Microsoft), in una scheda di servizio
che non va mai in primo piano e si chiude alla fine.

Il browser vive in LiveBridge: li' le letture girano sul suo event loop
(bind()). Gli altri processi (bot.py, daemon vocale) chiedono a LiveBridge
via HTTP locale con il token del Watch: Chromium non apre lo stesso profilo
da due processi insieme.

Selettori per ruolo ARIA e righe di testo, mai etichette localizzate.
L'agenda resta in cache 10 minuti: il promemoria calendario di bot.py chiede
ogni minuto e Outlook Web non deve ricaricarsi ogni minuto. Accesso scaduto:
nessun nuovo tentativo per 5 minuti, niente raffiche sulla pagina di login.
"""
import asyncio
import concurrent.futures
import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import httpx

from core import browser
from core.outlook import _BODY_CHARS, _SNIPPET_CHARS

ROOT = Path(__file__).resolve().parent.parent
PATH = "/internal/outlook-web"
# Indirizzo del proxy Defender for Cloud Apps, non outlook.office.com.
# Verificato dal vivo il 2026-10-27 sul profilo JARVIS: outlook.office.com
# finisce in un ciclo di login.microsoftonline.com/common/reprocess (centinaia
# di redirect, mai Outlook), il dominio .mcas.ms entra in 2-4 s anche a
# browser appena avviato. JARVIS_OWA_BASE per un altro tenant.
OWA_BASE = os.getenv("JARVIS_OWA_BASE", "https://outlook.cloud.microsoft.mcas.ms").rstrip("/")
MAIL_URL = f"{OWA_BASE}/mail/inbox"
# OWA ignora la data nell'URL (view/day/AAAA/M/G torna alla vista salvata):
# la settimana lavorativa corrente e' l'unica vista prevedibile.
CALENDAR_URL = f"{OWA_BASE}/calendar/view/workweek"
TIMEOUT_SEC = 90
CACHE_SEC = {"events": 600, "emails": 60, "unread": 60}
LOGIN_RETRY_SEC = 300
_ROWS_WAIT_MS = 15000
_CALENDAR_SETTLE_MS = 4000  # gli eventi arrivano dopo la griglia del giorno
_MAX_ROWS = 50

# Righe dell'elenco messaggi: testi foglia con grassetto (= non letta) e
# title. Verificato dal vivo il 2026-10-27: prima del mittente c'e' l'avatar
# con le iniziali, sempre in grassetto; il mittente ha l'indirizzo nel title;
# le icone sono caratteri dell'area privata Unicode.
_ROWS_JS = """() => [...document.querySelectorAll('[role=option]')].slice(0, %d).map(row => ({
  lines: (row.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean),
  leaves: [...row.querySelectorAll('span, div')].filter(el => !el.childElementCount && (el.textContent || '').trim())
    .map(el => ({text: el.textContent.trim(), title: el.getAttribute('title') || '',
                 bold: parseInt(getComputedStyle(el).fontWeight, 10) >= 600})),
}))""" % _MAX_ROWS

# Cartella selezionata (Posta in arrivo, dall'URL): l'ultimo numero del suo
# testo e' il conteggio non lette; nessun numero = zero.
_UNREAD_JS = """() => {
  const folder = document.querySelector('[role=treeitem][aria-selected=true]');
  if (!folder) return null;
  const numbers = (folder.innerText || '').match(/\\d+/g);
  return numbers ? parseInt(numbers[numbers.length - 1], 10) : 0;
}"""

# Eventi della vista giorno: l'etichetta accessibile contiene titolo e orari.
_EVENT_LABELS_JS = """() => [...document.querySelectorAll('[role=main] [aria-label]')]
  .map(el => el.getAttribute('aria-label') || '')
  .filter(label => label.includes(',') && /\\d{1,2}[:.]\\d{2}\\D+\\d{1,2}[:.]\\d{2}/.test(label))"""

_ICON_RE = re.compile("^[-\\s]*$")
_TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}/\d{1,2}\b")
_RANGE_RE = re.compile(
    r"(\d{1,2})[:.](\d{2})\s*([ap]\.?\s?m\.?)?\D{1,15}?(\d{1,2})[:.](\d{2})\s*([ap]\.?\s?m\.?)?", re.IGNORECASE)
_CONNECTOR_RE = re.compile(r"[\s,]*\b(?:dalle|dalle ore|da|ore|from|alle)\s*$", re.IGNORECASE)
_MONTHS = {name: number for number, names in enumerate((
    ("gennaio", "january"), ("febbraio", "february"), ("marzo", "march"), ("aprile", "april"),
    ("maggio", "may"), ("giugno", "june"), ("luglio", "july"), ("agosto", "august"),
    ("settembre", "september"), ("ottobre", "october"), ("novembre", "november"), ("dicembre", "december")),
    start=1) for name in names}
_MONTH = "(" + "|".join(_MONTHS) + ")"
_DATE_RES = (re.compile(r"\b(\d{1,2})\s+" + _MONTH + r",?\s+(\d{4})\b", re.IGNORECASE),
             re.compile(r"\b" + _MONTH + r"\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE))
_WEEKDAYS = {"lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
             "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


class OutlookWebError(Exception):
    pass


_loop: asyncio.AbstractEventLoop | None = None
_lock: asyncio.Lock | None = None
_cache: dict[tuple, tuple[float, object]] = {}
_login_retry_at = 0.0


def bind(loop: asyncio.AbstractEventLoop) -> None:
    """Chiamato da LiveBridge: questo processo possiede il browser JARVIS."""
    global _loop
    _loop = loop


def _email(row: dict) -> dict:
    if row.get("leaves"):
        return _email_from_leaves(row["leaves"])
    lines = row["lines"]
    received = next((line for line in lines[1:] if len(line) <= 24 and _TIME_RE.search(line)), "")
    rest = [line for line in lines[2:] if line != received]
    snippet = " ".join(rest)
    return dict(sender=lines[0] if lines else "sconosciuto", subject=lines[1] if len(lines) > 1 else "(nessun oggetto)",
                received=received, unread=bool(row.get("bold")),
                snippet=snippet[:_SNIPPET_CHARS] + ("…" if len(snippet) > _SNIPPET_CHARS else ""))


def _email_from_leaves(leaves: list[dict]) -> dict:
    leaves = [leaf for leaf in leaves if not _ICON_RE.match(leaf["text"])]
    sender_at = next((i for i, leaf in enumerate(leaves) if "@" in leaf["title"]), None)
    if sender_at is not None:
        leaves = leaves[sender_at:]  # via l'avatar
    elif len(leaves) > 2 and len(leaves[0]["text"]) <= 3 and leaves[0]["text"].isupper():
        leaves = leaves[1:]  # iniziali dell'avatar
    texts = [leaf["text"] for leaf in leaves]
    received = next((text for text in texts[1:] if len(text) <= 24 and _TIME_RE.search(text)), "")
    rest = [text for text in texts[1:] if text != received]
    snippet = " ".join(rest[1:])
    return dict(sender=texts[0] if texts else "sconosciuto", subject=rest[0] if rest else "(nessun oggetto)",
                received=received, unread=any(leaf["bold"] for leaf in leaves),
                snippet=snippet[:_SNIPPET_CHARS] + ("…" if len(snippet) > _SNIPPET_CHARS else ""))


def _label_date(label: str) -> dt.date | None:
    """Data scritta nell'etichetta ("Mercoledì, 28 Ottobre, 2026" o "October 28, 2026")."""
    for number, pattern in enumerate(_DATE_RES):
        match = pattern.search(label)
        if match:
            day, month, year = (match[1], match[2], match[3]) if number == 0 else (match[2], match[1], match[3])
            try:
                return dt.date(int(year), _MONTHS[month.lower()], int(day))
            except ValueError:
                return None
    return None


def _hour(hours: str, minutes: str, meridiem: str | None) -> tuple[int, int]:
    h = int(hours)
    if meridiem and meridiem.lower().startswith("p") and h < 12:
        h += 12
    if meridiem and meridiem.lower().startswith("a") and h == 12:
        h = 0
    return h, int(minutes)


def _parse_event(label: str, day: dt.date) -> dict | None:
    match = _RANGE_RE.search(label)
    if not match:
        return None
    labelled = _label_date(label)
    if labelled and labelled != day:
        return None  # Outlook Web puo' mostrare la settimana: solo il giorno chiesto
    start_h, start_m = _hour(match[1], match[2], match[3] or match[6])
    end_h, end_m = _hour(match[4], match[5], match[6])
    if start_h > 23 or end_h > 24 or start_m > 59 or end_m > 59:
        return None
    start = dt.datetime.combine(day, dt.time(start_h, start_m))
    end = dt.datetime.combine(day, dt.time(0, 0)) + dt.timedelta(hours=end_h, minutes=end_m)
    if end <= start:
        end += dt.timedelta(days=1)  # evento che finisce dopo mezzanotte
    subject = _CONNECTOR_RE.sub("", label[:match.start()]).strip(" ,")
    if not subject:  # etichetta che comincia con l'orario: il titolo viene dopo
        subject = next((part.strip() for part in label[match.end():].split(",") if part.strip()), "")
        if subject.casefold() in _WEEKDAYS:
            return None  # fascia vuota della griglia ("Dalle 23:00 alle 23:30, Martedì, ...")
    return dict(subject=subject or "(senza titolo)", start=start.isoformat(), end=end.isoformat(), location="")


async def _wait_rows(page) -> None:
    try:
        await page.locator("[role=option]").first.wait_for(timeout=_ROWS_WAIT_MS)
    except Exception:
        pass  # casella vuota: nessuna riga


async def _emails(count: int = 8, unread_only: bool = False) -> list[dict]:
    async with browser.get_agent().service_page(MAIL_URL, "[role=main]") as page:
        await _wait_rows(page)
        rows = await page.evaluate(_ROWS_JS)
    emails = [_email(row) for row in rows if row["lines"]]
    if unread_only:
        emails = [e for e in emails if e["unread"]]
    return emails[:max(1, min(int(count), _MAX_ROWS))]


async def _unread() -> int:
    async with browser.get_agent().service_page(MAIL_URL, "[role=main]") as page:
        await _wait_rows(page)
        count = await page.evaluate(_UNREAD_JS)
        if count is None:
            count = sum(1 for row in await page.evaluate(_ROWS_JS) if _email(row)["unread"])
    return int(count)


async def _find(query: str, unread_only: bool = False) -> dict | None:
    needle = str(query).strip().casefold()
    if not needle:
        return None
    async with browser.get_agent().service_page(MAIL_URL, "[role=main]") as page:
        await _wait_rows(page)
        rows = [_email(row) for row in await page.evaluate(_ROWS_JS)]
        index = next((i for i, email in enumerate(rows) if (email["unread"] or not unread_only)
                      and needle in f"{email['sender']}\n{email['subject']}".casefold()), None)
        if index is None:
            return None
        await page.locator("[role=option]").nth(index).click(timeout=5000)
        # Corpo nel riquadro di lettura (verificato dal vivo il 2026-10-27): il
        # primo [role=document] della pagina e' l'app intera, barre comprese.
        document = page.locator("#ReadingPaneContainerId [role=document]").first
        try:
            await document.wait_for(timeout=10000)
            body = (await document.inner_text()).strip()
        except Exception:  # noqa: BLE001 — riquadro cambiato: almeno mittente e oggetto
            body = ""
    email = rows[index]
    if len(body) > _BODY_CHARS:
        body = body[:_BODY_CHARS].rstrip() + "…"
    return dict(sender=email["sender"], subject=email["subject"], received=email["received"], body=body)


async def _events(day: str) -> list[dict]:
    date = dt.date.fromisoformat(day)
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    if not monday <= date <= monday + dt.timedelta(days=4):
        raise OutlookWebError("Outlook Web legge solo l'agenda della settimana lavorativa corrente")
    async with browser.get_agent().service_page(CALENDAR_URL, "[role=main]") as page:
        await page.wait_for_timeout(_CALENDAR_SETTLE_MS)
        labels = await page.evaluate(_EVENT_LABELS_JS)
    events = {}
    for label in labels:
        event = _parse_event(label, date)
        if event:
            events.setdefault((event["subject"], event["start"]), event)
    return sorted(events.values(), key=lambda e: e["start"])


_ACTIONS = {"emails": _emails, "unread": _unread, "find": _find, "events": _events}


def _clean_params(action: str, params: dict) -> dict:
    if action == "emails":
        return dict(count=int(params.get("count", 8)), unread_only=bool(params.get("unread_only", False)))
    if action == "find":
        query = params.get("query")
        if not isinstance(query, str) or not 0 < len(query) <= 200:
            raise OutlookWebError("ricerca non valida")
        return dict(query=query, unread_only=bool(params.get("unread_only", False)))
    if action == "events":
        try:
            return dict(day=dt.date.fromisoformat(str(params.get("day"))).isoformat())
        except ValueError as error:
            raise OutlookWebError("giorno non valido") from error
    return {}


async def run(action: str, params: dict | None = None):
    """Esegue una lettura sul loop che possiede il browser. Risultati JSON
    (anche per le richieste HTTP degli altri processi)."""
    global _lock, _login_retry_at
    if action not in _ACTIONS:
        raise OutlookWebError("azione non valida")
    params = _clean_params(action, params or {})
    if time.monotonic() < _login_retry_at:
        raise OutlookWebError("serve di nuovo l'accesso Microsoft nel browser JARVIS: apri Outlook dai Collegamenti")
    key = (action, json.dumps(params, sort_keys=True))
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    _lock = _lock or asyncio.Lock()
    async with _lock:  # una scheda di servizio alla volta
        try:
            result = await _ACTIONS[action](**params)
        except PermissionError as error:
            _login_retry_at = time.monotonic() + LOGIN_RETRY_SEC
            raise OutlookWebError("serve di nuovo l'accesso Microsoft nel browser JARVIS: "
                                  "apri Outlook dai Collegamenti") from error
        except OutlookWebError:
            raise
        except Exception as error:  # noqa: BLE001 — pagina cambiata, rete, browser chiuso
            raise OutlookWebError(f"lettura non riuscita ({type(error).__name__})") from error
    if CACHE_SEC.get(action):
        _cache[key] = (time.monotonic() + CACHE_SEC[action], result)
    return result


def _live_endpoint() -> tuple[int, str]:
    """Porta e token di LiveBridge, letti come fa core/live_server.py::main."""
    try:
        config = json.loads((ROOT / ".live-config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        config = {}
    token = os.getenv("JARVIS_WATCH_TOKEN", "")
    if not token:
        try:
            token = (ROOT / ".watch-token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    return int(config.get("port", 8765)), token


def _remote(action: str, params: dict):
    port, token = _live_endpoint()
    if not token:
        raise OutlookWebError("LiveBridge non configurato su questo PC")
    try:
        # trust_env=False: niente proxy di sistema verso 127.0.0.1.
        with httpx.Client(timeout=TIMEOUT_SEC, trust_env=False) as client:
            response = client.post(f"http://127.0.0.1:{port}{PATH}", json={"action": action, "params": params},
                                   headers={"Authorization": f"Bearer {token}"})
        body = response.json()
    except httpx.HTTPError as error:
        raise OutlookWebError("LiveBridge non raggiungibile") from error
    except ValueError as error:
        raise OutlookWebError(f"risposta LiveBridge non valida (HTTP {response.status_code})") from error
    if not body.get("ok"):
        raise OutlookWebError(body.get("error") or f"HTTP {response.status_code}")
    return body["result"]


def call_sync(action: str, **params):
    """Da un thread qualunque: sul loop del browser se questo processo lo
    possiede (LiveBridge), altrimenti via LiveBridge."""
    if _loop is None:
        return _remote(action, params)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        raise OutlookWebError("lettura sincrona dal loop del browser non consentita")
    try:
        future = asyncio.run_coroutine_threadsafe(run(action, params), _loop)
    except RuntimeError as error:  # LiveBridge in chiusura
        raise OutlookWebError("browser JARVIS non disponibile") from error
    try:
        return future.result(TIMEOUT_SEC)
    except concurrent.futures.TimeoutError as error:
        future.cancel()
        raise OutlookWebError("Outlook Web non risponde") from error
