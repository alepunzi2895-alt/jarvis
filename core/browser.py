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

from playwright.async_api import async_playwright, BrowserContext, Playwright

BROWSER_BLOCK_RE = re.compile(r"```browser\s*\n(.*?)\n```", re.DOTALL)

PROFILE_DIR = Path(os.getenv("JARVIS_HOME", str(Path(__file__).parent.parent))) / ".browser_profile"

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

    async def open(self, url: str) -> str:
        context = await self._ensure_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        return f"Aperto {url}."

    async def search(self, engine: str, query: str, open_first_result: bool = True) -> str:
        if engine not in SEARCH_URLS:
            return f'Motore "{engine}" non supportato (solo google/youtube).'
        context = await self._ensure_context()
        page = await context.new_page()
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
        if not context.pages:
            return b""
        return await context.pages[-1].screenshot()

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
