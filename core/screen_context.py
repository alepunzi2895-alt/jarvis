"""
JARVIS — "guarda cosa sto facendo": schermo intero (desktop), o Teams
(browser JARVIS, sessione persistente). Stesso pattern di
core/voice/camera.py: rilevamento testuale -> cattura locale -> passata
come image_b64 allo stesso canale gia' usato per la webcam (nessuna
immagine nuova da far "richiedere" a Claude via blocco — e' semplicemente
gia' allegata al messaggio prima di chiamarlo).

Outlook NON passa piu' di qui (vedi core/outlook.py, COM su Outlook
desktop — dati veri invece di uno screenshot da far interpretare a
Claude, e zero login browser da rifare).

Teams richiede che Alessandro abbia gia' fatto login UNA VOLTA nel browser
di JARVIS (stesso .browser_profile persistente di core/browser.py —
headless=False, la finestra e' visibile, il login SSO/MFA lo fa lui a
mano la prima volta, la sessione poi resta salvata). Se non e' mai stato
fatto, la schermata catturata mostrera' la pagina di login, non un errore
silenzioso — e' Claude a doverlo notare guardando l'immagine.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re

from core import browser
from core.executor_singleton import executor as _system_executor

TEAMS_URL = os.getenv("JARVIS_TEAMS_URL", "https://teams.microsoft.com/v2/")

# Pagina SPA pesante (Teams): "domcontentloaded" (usato da browser.py::open)
# spesso arriva prima che il contenuto vero sia renderizzato via JS — un'attesa
# fissa dopo la navigazione evita uno screenshot della sola shell/schermata di
# caricamento. Valore di partenza, non misurato dal vivo su questa macchina:
# da aggiustare se lo screenshot arriva ancora vuoto/a meta' caricamento.
_SPA_RENDER_WAIT_SECONDS = 3

_TEAMS_RE = re.compile(r"\bteams\b", re.IGNORECASE)
_SCREEN_RE = re.compile(
    r"\bschermo\b|\bschermat[ae]\b|\bdesktop\b|\bdatabricks\b|\bgenie\b"
    r"|\bcosa\s+(sto\s+facendo|vedo|c'e'|c’e')\b",
    re.IGNORECASE,
)


def target_for(text: str) -> str | None:
    """'teams'/'screen' se il testo chiede di vedere una di queste cose,
    altrimenti None. 'databricks'/'genie' senza altro contesto cadono su
    'screen': JARVIS non sa quale dashboard/notebook specifico intendi (ne'
    ha un modo di aprire una conversazione Genie Code precisa), guarda cosa
    hai gia' aperto tu — es. "leggimi l'ultima risposta di Genie Code"
    presuppone che la finestra sia gia' in primo piano. Le mail/Outlook non
    passano di qui, vedi core/outlook.py (intent dedicato, dati veri via COM
    invece di uno screenshot)."""
    if _TEAMS_RE.search(text):
        return "teams"
    if _SCREEN_RE.search(text):
        return "screen"
    return None


async def capture(target: str) -> str | None:
    """JPEG/PNG base64 per il target indicato, o None se la cattura fallisce."""
    if target == "teams":
        return await _capture_browser_page(TEAMS_URL)
    if target == "screen":
        return await asyncio.to_thread(_capture_desktop)
    return None


async def _capture_browser_page(url: str) -> str | None:
    agent = browser.get_agent()
    try:
        await agent.open(url)
        await asyncio.sleep(_SPA_RENDER_WAIT_SECONDS)
        png = await agent.screenshot()
    except Exception:
        return None
    return base64.b64encode(png).decode("ascii") if png else None


def _capture_desktop() -> str | None:
    result = _system_executor.screenshot()
    if not result.ok:
        return None
    try:
        with open(result.stdout, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None
