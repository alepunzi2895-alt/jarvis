"""
JARVIS — controllo browser reale (Playwright), contesto persistente cosi'
le sessioni restano loggate.

Sicurezza tramite vocabolario limitato, non tramite un filtro sulle azioni
pericolose: solo navigazione/lettura (apri un URL, cerca e apri il primo
risultato, screenshot) — niente click/fill generico su selettori arbitrari
in questa versione. Azioni che scrivono/inviano/comprano si aggiungeranno
in futuro solo dietro lo stesso meccanismo di conferma di SystemExecutor,
se e quando servira' davvero.

Stesso pattern di core/brain.py: Claude emette un blocco ```browser``` in
fondo alla risposta quando capisce che l'utente vuole navigare un sito
vero; extract_and_execute() lo estrae, esegue, ripulisce il testo.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, BrowserContext, Playwright

BROWSER_BLOCK_RE = re.compile(r"```browser\s*\n(.*?)\n```", re.DOTALL)

PROFILE_DIR = Path(os.getenv("JARVIS_HOME", str(Path(__file__).parent.parent))) / ".browser_profile"

# Nessun indirizzo locale e' mai un sito vero da navigare (dashboard, second
# brain, webcam sono concetti locali, non pagine web — il SYSTEM prompt lo
# dice esplicitamente a Claude, ma un'istruzione a parole non e' bastata: lo
# stesso bug ("apro la dashboard" -> ERR_CONNECTION_REFUSED su localhost:3000,
# che non e' nemmeno un server in esecuzione) si e' ripresentato tre volte
# (15/07 mattina, 15/07 sera, 16/07) nonostante il prompt lo vietasse gia'.
# Bloccato qui, a livello di codice, invece di continuare a fidarsi del solo
# prompt.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
}

RESULT_SELECTORS = {
    "google": "#search a h3",
    "youtube": "ytd-video-renderer a#video-title",
}


class BrowserAgent:
    def __init__(self):
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    async def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            self._playwright = await async_playwright().start()
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, viewport=None
            )
        return self._context

    async def _reset(self) -> None:
        """Il contesto/browser puo' essere stato chiuso dall'esterno (finestra
        chiusa a mano, crash) senza che self._context lo sappia — si riparte
        da zero invece di restare bloccati su un riferimento morto."""
        self._context = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def _new_page(self):
        context = await self._ensure_context()
        try:
            return await context.new_page()
        except Exception:
            await self._reset()
            context = await self._ensure_context()
            return await context.new_page()

    async def open(self, url: str) -> str:
        if (urlparse(url).hostname or "") in _LOCAL_HOSTS:
            return (
                "Non apro un browser per un indirizzo locale: dashboard, second brain e "
                "webcam sono gestiti in locale, non sono siti da navigare."
            )
        page = await self._new_page()
        await page.goto(url, wait_until="domcontentloaded")
        return f"Aperto {url}."

    async def search(self, engine: str, query: str, open_first_result: bool = True) -> str:
        if engine not in SEARCH_URLS:
            return f'Motore "{engine}" non supportato (solo google/youtube).'
        page = await self._new_page()
        url = SEARCH_URLS[engine].format(query=query.replace(" ", "+"))
        await page.goto(url, wait_until="domcontentloaded")

        if not open_first_result:
            return f'Cercato "{query}" su {engine}.'

        try:
            selector = RESULT_SELECTORS[engine]
            await page.wait_for_selector(selector, timeout=8000)
            await page.locator(selector).first.click()
            return f'Aperto il primo risultato per "{query}" su {engine}.'
        except Exception:
            return f'Cercato "{query}" su {engine}, ma non ho trovato un risultato da aprire da solo.'

    async def screenshot(self) -> bytes:
        context = await self._ensure_context()
        try:
            if not context.pages:
                return b""
            return await context.pages[-1].screenshot()
        except Exception:
            await self._reset()
            return b""

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


_agent: BrowserAgent | None = None


def get_agent() -> BrowserAgent:
    global _agent
    if _agent is None:
        _agent = BrowserAgent()
    return _agent


async def extract_and_execute(text: str) -> str:
    """Estrae ed esegue ogni blocco ```browser```, ritorna il testo ripulito
    con l'esito dell'azione in fondo."""
    matches = list(BROWSER_BLOCK_RE.finditer(text))
    if not matches:
        return text

    agent = get_agent()
    outcomes: list[str] = []
    for m in matches:
        try:
            action = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue

        kind = action.get("action")
        try:
            if kind == "open" and action.get("url"):
                outcomes.append(await agent.open(action["url"]))
            elif kind == "search" and action.get("query"):
                outcomes.append(
                    await agent.search(
                        action.get("engine", "google"),
                        action["query"],
                        action.get("open_first_result", True),
                    )
                )
        except Exception as e:  # noqa: BLE001
            outcomes.append(f"Errore browser: {e}")

    cleaned = BROWSER_BLOCK_RE.sub("", text).strip()
    if outcomes:
        cleaned = f"{cleaned}\n\n{' '.join(outcomes)}".strip()
    return cleaned
