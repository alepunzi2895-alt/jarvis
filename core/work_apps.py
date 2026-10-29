"""
JARVIS — apertura automatica delle app di lavoro IVECO.

Teams e Outlook: se l'app desktop e' gia' aperta si usa quella, altrimenti la
versione web nel browser JARVIS. Databricks QAS, Azure DevOps e ServiceNow
sono solo web. Si apre solo cio' che manca: mai ricaricare una scheda gia'
aperta, mai portare il browser in primo piano (gira anche alle 09:25 senza
nessuno davanti al PC).

Scatta da: apertura del pannello IVECO, domanda su IVECO, 5 minuti prima del
recap (core/iveco.py::recap_loop). Sostituisce il pannello "Collegamenti".
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time

import psutil

LOG = logging.getLogger(__name__)

WORK_APPS = ("teams", "outlook", "databricks_qas", "devops", "servicenow")

# Nomi dei processi dell'app desktop (Teams nuovo e classico, Outlook classico).
_DESKTOP_PROCESSES = {
    "teams": {"ms-teams.exe", "teams.exe"},
    "outlook": {"outlook.exe"},
}

# Domanda "su IVECO": il nome del cliente o dell'agente che ci lavora.
IVECO_RE = re.compile(r"\b(?:iveco|ivg\s*agent)\b", re.IGNORECASE)

# Dopo un tentativo la stessa app non si riprova per un po': un accesso scaduto
# o una pagina lenta non devono riaprire il login a ogni domanda.
RETRY_AFTER_SEC = 300
_attempted: dict[str, float] = {}
_background: set[asyncio.Task] = set()


def desktop_running(app: str) -> bool:
    """True se l'app desktop (solo Teams e Outlook) ha un processo attivo."""
    names = _DESKTOP_PROCESSES.get(app)
    if not names:
        return False
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").lower() in names:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


# Avvio dell'app desktop se non e' aperta: Teams nuovo via AppsFolder, Outlook via App Paths.
_DESKTOP_LAUNCH = {
    "teams": r"shell:AppsFolder\MSTeams_8wekyb3d8bbwe!MSTeams",
    "outlook": "outlook.exe",
}


def launch_desktop(app: str) -> bool:
    """Avvia l'app desktop con l'account Windows (SSO). False se non parte."""
    target = _DESKTOP_LAUNCH.get(app)
    if not target:
        return False
    try:
        os.startfile(target)  # solo Windows
        return True
    except OSError:
        LOG.exception("Avvio app desktop fallito: %s", app)
        return False


def web_urls() -> dict[str, str]:
    """Indirizzi web delle app configurate (Databricks QAS solo se nel .env)."""
    from core import databricks, servicenow
    urls = {
        "teams": os.getenv("JARVIS_TEAMS_URL", "https://teams.microsoft.com/v2/"),
        "outlook": "https://outlook.office.com/mail/",
        "servicenow": servicenow.LIST_URL,
    }
    host = databricks._ENVIRONMENTS["qas"]["host"]
    if host:
        urls["databricks_qas"] = host
    return urls


async def _open_one(app: str, urls: dict[str, str], agent, force: bool) -> dict:
    if app in _DESKTOP_PROCESSES:
        if await asyncio.to_thread(desktop_running, app):
            return dict(app=app, ok=True, state="desktop", message=f"{app}: uso l'app desktop gia' aperta.")
        # PC acceso ma app desktop chiusa: la avvio (login Windows), web solo se non parte.
        if await asyncio.to_thread(launch_desktop, app):
            return dict(app=app, ok=True, state="desktop avviato", message=f"{app}: app desktop avviata.")
    if app == "devops":
        from core import azure_devops
        url = azure_devops.settings()["project_url"]
        if agent.is_open(url):
            return dict(app=app, ok=True, state="aperto", message="devops: gia' aperto.")
        # Token per le API dei deploy via Azure CLI (login solo se scaduto).
        login = await asyncio.to_thread(azure_devops.connect)
        message = f"{login} {await agent.open(url, foreground=force)}"
        return dict(app=app, ok=True, state="aperto ora", message=message)
    url = urls.get(app)
    if not url:
        return dict(app=app, ok=False, state="non configurato", message="Databricks QAS non configurato nel file .env.")
    if agent.is_open(url):
        return dict(app=app, ok=True, state="aperto", message=f"{app}: gia' aperto.")
    return dict(app=app, ok=True, state="aperto ora", message=await agent.open(url, foreground=force))


async def ensure_open(apps=None, *, force: bool = False) -> list[dict]:
    """Apre nel browser JARVIS le app che non lo sono gia'. `force` (comando
    esplicito di Alessandro): niente attesa tra i tentativi e browser in primo piano."""
    from core.browser import get_agent
    agent = get_agent()
    results = []
    for app in apps or WORK_APPS:
        if not force and time.monotonic() - _attempted.get(app, -RETRY_AFTER_SEC) < RETRY_AFTER_SEC:
            results.append(dict(app=app, ok=True, state="recente", message=f"{app}: controllato da poco."))
            continue
        _attempted[app] = time.monotonic()
        try:
            urls = await asyncio.to_thread(web_urls)
            results.append(await _open_one(app, urls, agent, force))
        except Exception:  # noqa: BLE001 — una app giu' non ferma le altre
            LOG.exception("Apertura servizio fallita: %s", app)
            results.append(dict(app=app, ok=False, state="errore", message=f"Non riesco ad aprire {app}."))
    return results


def ensure_open_later(apps=None) -> None:
    """Avvia ensure_open senza attenderlo (domande, apertura pannello, recap)."""
    task = asyncio.ensure_future(ensure_open(apps))
    _background.add(task)
    task.add_done_callback(_background.discard)
