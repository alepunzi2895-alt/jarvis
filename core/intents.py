"""
JARVIS — intenti di controllo del sistema operativo, riconosciuti dal testo
PRIMA di interpellare Claude: azioni immediate, deterministiche, a costo e
latenza zero (nessun giro di `claude -p`). Stesso principio
dell'intercettazione lato client in web/public/app.js (le finestre della
dashboard), esteso qui alle azioni REALI sul sistema operativo che il
browser non potra' mai eseguire.

Filosofia sicurezza: azioni reversibili/innocue (aprire/chiudere un'app,
volume, blocco schermo, mostra desktop, screenshot) eseguono subito su ogni
canale. Azioni irreversibili (spegnimento/riavvio/logout) passano SEMPRE
dalla conferma esplicita gia' presente in SystemExecutor — e dal canale
vocale sono rifiutate del tutto (nessun flusso di conferma a voce ha senso
per un comando che un rumore/misascolto potrebbe innescare da solo),
rimandate a Telegram/dashboard dove /confirm esiste gia'.

Per non "rubare" a Claude richieste composte o sfumate ("apri VS code e poi
crea un file X"), il riconoscimento si applica solo a frasi brevi (vedi
_MAX_WORDS): frasi piu' lunghe passano sempre da Claude, che puo' comunque
eseguire le stesse azioni tramite un blocco ```system``` (core/system_actions.py).
"""

from __future__ import annotations

import re
import threading

from core import turso
from core.system_executor import APP_REGISTRY, DYNAMIC_APP_NAMES, KNOWN_USER_APPS, SystemExecutor

_MAX_WORDS = 10  # oltre questa soglia, non e' un comando semplice: passa da Claude

_APP_NAMES = sorted(
    {*APP_REGISTRY.keys(), *KNOWN_USER_APPS.keys(), *DYNAMIC_APP_NAMES}, key=len, reverse=True
)

_OPEN_VERBS = r"apri|apra|avvia|avvii|accendi|accenda|lancia|lanci"
_CLOSE_VERBS = r"chiudi|chiuda|termina|termini|spegni|spegnere"

_SHUTDOWN_RE = re.compile(r"\bspegni\w*\b.*\b(pc|computer|windows|sistema)\b", re.IGNORECASE)
_RESTART_RE = re.compile(r"\briavvi\w*\b.*\b(pc|computer|windows|sistema)\b", re.IGNORECASE)
_LOGOFF_RE = re.compile(
    r"\b(disconnetti|scollega)\w*\b.*\b(utente|sessione|account)\b|\bfai il logout\b", re.IGNORECASE
)

_VOLUME_UP_RE = re.compile(r"\b(alza|aumenta)\w*\b.*\bvolume\b", re.IGNORECASE)
_VOLUME_DOWN_RE = re.compile(r"\b(abbassa|diminuisci)\w*\b.*\bvolume\b", re.IGNORECASE)
_VOLUME_MUTE_RE = re.compile(r"\b(muta|silenzia|zittisci)\w*\b.*\bvolume\b|\btogli l.?audio\b", re.IGNORECASE)
_VOLUME_UNMUTE_RE = re.compile(r"\briattiva\w*\b.*\baudio\b|\btorna l.?audio\b", re.IGNORECASE)

_LOCK_RE = re.compile(r"\bblocca\w*\b.*\b(schermo|pc|computer|sessione)\b", re.IGNORECASE)
_SHOW_DESKTOP_RE = re.compile(r"\bmostra\w*\b.*\bdesktop\b|\bminimizza tutto\b", re.IGNORECASE)
_SCREENSHOT_RE = re.compile(
    r"\b(fai|scatta|cattura)\w*\b.*\bscreenshot\b|\bcattura\w*\b.*\bschermo\b", re.IGNORECASE
)


def parse_intent(text: str) -> dict | None:
    """Ritorna un descrittore d'azione se il testo e' un comando di sistema
    semplice e riconosciuto, altrimenti None (la richiesta prosegue verso
    Claude come sempre)."""
    t = text.strip()
    if not t or len(t.split()) > _MAX_WORDS:
        return None

    if _SHUTDOWN_RE.search(t):
        return {"type": "power", "mode": "shutdown"}
    if _RESTART_RE.search(t):
        return {"type": "power", "mode": "restart"}
    if _LOGOFF_RE.search(t):
        return {"type": "power", "mode": "logoff"}

    if _VOLUME_UP_RE.search(t):
        return {"type": "volume", "direction": "up"}
    if _VOLUME_DOWN_RE.search(t):
        return {"type": "volume", "direction": "down"}
    if _VOLUME_MUTE_RE.search(t):
        return {"type": "volume", "direction": "mute"}
    if _VOLUME_UNMUTE_RE.search(t):
        return {"type": "volume", "direction": "unmute"}

    if _LOCK_RE.search(t):
        return {"type": "lock"}
    if _SHOW_DESKTOP_RE.search(t):
        return {"type": "show_desktop"}
    if _SCREENSHOT_RE.search(t):
        return {"type": "screenshot"}

    low = t.lower()
    for app in _APP_NAMES:
        if re.search(rf"\b{re.escape(app)}\b", low):
            if re.search(rf"\b({_CLOSE_VERBS})\b", low):
                return {"type": "close_app", "name": app}
            if re.search(rf"\b({_OPEN_VERBS})\b", low):
                return {"type": "open_app", "name": app}

    return None


_POWER_LABELS = {"shutdown": "spegnere il PC", "restart": "riavviare il PC", "logoff": "disconnettere l'utente"}


def execute_intent(
    intent: dict, executor: SystemExecutor, voice: bool, workspace: str = "jarvis", raw_text: str = ""
) -> str:
    """Esegue l'azione, logga l'interazione nel second brain, ritorna una frase
    pronta da mostrare/pronunciare.

    Il log e' qui (non nei 3 chiamanti: bot.py, core/web_bridge.py,
    core/voice/daemon.py) per avere un solo punto d'ingresso: questi comandi
    rapidi non passano MAI da Claude (e' il loro scopo — zero costo/latenza),
    quindi senza questo il grafo second brain non rifletterebbe mai "apri
    chrome"/"che ore sono"/ecc. — richiesta esplicita di Alessandro
    (2026-07-16): "ogni interazione e domanda aggiorna il grafo".

    Il log gira su un thread a parte, senza attenderlo: e' una scrittura
    Turso (~1s) che altrimenti romperebbe la garanzia di "zero latenza" che
    e' la ragion d'essere di questo modulo. Un thread semplice invece di
    asyncio perche' questa funzione e' chiamata sia da contesti async
    (bot.py, core/web_bridge.py) sia da un loop sincrono puro
    (core/voice/daemon.py) — un thread funziona identico in entrambi."""
    response = _execute(intent, executor, voice)
    if turso.ENABLED:
        from core import brain  # import qui: evita di caricare brain.py se turso e' disabilitato

        label = raw_text or f"[comando] {intent.get('type', '?')}"
        threading.Thread(target=brain.log_interaction, args=(label, workspace, "voice" if voice else "text"), daemon=True).start()
    return response


def _execute(intent: dict, executor: SystemExecutor, voice: bool) -> str:
    kind = intent["type"]
    sir = ", Signore" if voice else ""

    if kind == "power":
        if voice:
            return (
                "Per sicurezza non gestisco spegnimento, riavvio o logout da "
                "comando vocale, Signore. Lo confermi da Telegram o dalla dashboard."
            )
        result = executor.power_action(intent["mode"])
        if result.needs_confirmation:
            label = _POWER_LABELS[intent["mode"]]
            return (
                f"Per {label} serve conferma esplicita. Scrivi /confirm {result.token} "
                f"per procedere o /deny {result.token} per annullare."
            )
        return "Fatto." if result.ok else f"Errore: {result.stderr}"

    if kind == "volume":
        result = executor.volume(intent["direction"])
        return f"Fatto{sir}." if result.ok else f"Errore volume: {result.stderr}"

    if kind == "lock":
        result = executor.lock_workstation()
        return f"Schermo bloccato{sir}." if result.ok else f"Errore: {result.stderr}"

    if kind == "show_desktop":
        result = executor.show_desktop()
        return f"Fatto{sir}." if result.ok else f"Errore: {result.stderr}"

    if kind == "screenshot":
        result = executor.screenshot()
        return f"Screenshot salvato in {result.stdout}." if result.ok else f"Errore screenshot: {result.stderr}"

    if kind == "open_app":
        result = executor.open_app(intent["name"])
        return f"Apro {intent['name']}{sir}." if result.ok else f"Non trovo {intent['name']}: {result.stderr}"

    if kind == "close_app":
        result = executor.close_app(intent["name"])
        return f"Chiudo {intent['name']}{sir}." if result.ok else f"{intent['name']}: {result.stderr}"

    return "Comando riconosciuto ma non ancora gestito."
