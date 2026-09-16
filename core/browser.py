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

from core.win_focus import bring_matching_to_foreground_bg

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

# "voglio poter leggere e capire cosa c'e' sulla pagina... e anche
# interagire, es aprire genie code e scrivere un input" (2026-09-15):
# read/click/type, sempre e solo sull'ultima pagina della NOSTRA sessione
# Playwright (context.pages[-1], stesso pattern gia' usato da screenshot())
# — mai sul browser normale dell'utente, che Playwright non puo' toccare.
# "click per testo visibile" invece di un selettore CSS/XPath arbitrario:
# stesso principio di vocabolario limitato del resto del modulo — Claude
# descrive COSA vuole cliccare in linguaggio naturale ("Genie Code"), non
# inventa una query DOM che potrebbe colpire l'elemento sbagliato.
_READ_MAX_CHARS = 6000
_INPUT_SELECTOR = "textarea, input[type='text'], input:not([type]), [contenteditable='true']"

# "bozze Teams/mail da approvare, mai invio automatico" (richiesta esplicita
# di Alessandro, 2026-09-16, estensione della regola gia' in CLAUDE.md "mai
# inviare messaggi a clienti senza conferma", qui allargata a chiunque via
# Teams). Applicata a livello di codice, non solo di prompt — stesso
# principio gia' in uso per `git push` in core/claude_bridge.py: anche se
# Claude (o un bug nel prompt) chiedesse submit=true su questi domini,
# type_text() lo ignora e lascia il testo scritto ma non inviato.
_DRAFT_ONLY_HOSTS = ("teams.microsoft.com", "outlook.office.com", "outlook.office365.com", "outlook.live.com")


def _is_draft_only_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith(f".{h}") for h in _DRAFT_ONLY_HOSTS)


def _clean_page_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(cleaned) > _READ_MAX_CHARS:
        cleaned = cleaned[:_READ_MAX_CHARS].rstrip() + "…"
    return cleaned

# "il comando apri databricks in test non mi apre questo link" (2026-09-15):
# la navigazione in se' funzionava (verificato dal vivo: pagina raggiunta,
# titolo corretto), ma bot.py gira come task pianificato Windows senza
# focus proprio — la finestra Chromium di Playwright (headless=False,
# quindi VISIBILE) puo' aprirsi dietro le altre senza che l'utente se ne
# accorga, esattamente come gia' risolto per core/system_executor.py::
# open_app. Qui il PID non e' direttamente esposto da Playwright per un
# contesto persistente (context.browser non ha .process nell'API async) —
# trovato invece per sottostringa nella cmdline, unica per il nostro
# profilo anche con altre finestre Chrome dell'utente gia' aperte
# (verificato dal vivo: EnumWindows + AttachThreadInput funziona anche
# quando ci sono due processi chrome.exe visibili contemporaneamente).
_PROFILE_MARKER = PROFILE_DIR.name  # ".browser_profile" - distintivo, non l'intero path (separatori piu' fragili)


def _bring_browser_to_foreground() -> None:
    bring_matching_to_foreground_bg(_PROFILE_MARKER)


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
        _bring_browser_to_foreground()
        return f"Aperto {url}."

    async def search(self, engine: str, query: str, open_first_result: bool = True) -> str:
        if engine not in SEARCH_URLS:
            return f'Motore "{engine}" non supportato (solo google/youtube).'
        page = await self._new_page()
        url = SEARCH_URLS[engine].format(query=query.replace(" ", "+"))
        await page.goto(url, wait_until="domcontentloaded")
        _bring_browser_to_foreground()

        if not open_first_result:
            return f'Cercato "{query}" su {engine}.'

        try:
            selector = RESULT_SELECTORS[engine]
            await page.wait_for_selector(selector, timeout=8000)
            await page.locator(selector).first.click()
            return f'Aperto il primo risultato per "{query}" su {engine}.'
        except Exception:
            return f'Cercato "{query}" su {engine}, ma non ho trovato un risultato da aprire da solo.'

    async def read(self) -> str:
        """Testo visibile dell'ultima pagina aperta nella sessione — cosi'
        Claude puo' "vedere" cosa c'e' (es. l'ultima risposta di Genie Code)
        senza dover interpretare uno screenshot per ogni domanda."""
        context = await self._ensure_context()
        if not context.pages:
            return "Nessuna pagina aperta nel browser di JARVIS."
        page = context.pages[-1]
        try:
            text = await page.inner_text("body")
        except Exception as e:  # noqa: BLE001
            return f"Impossibile leggere la pagina: {e}"
        return _clean_page_text(text) or "(pagina vuota o senza testo visibile)"

    async def click(self, label: str) -> str:
        """Clicca il primo elemento visibile che contiene il testo dato
        (non un selettore CSS/XPath — vedi nota sul vocabolario limitato)."""
        context = await self._ensure_context()
        if not context.pages:
            return "Nessuna pagina aperta da cui cliccare."
        page = context.pages[-1]
        try:
            await page.get_by_text(label, exact=False).first.click(timeout=5000)
            _bring_browser_to_foreground()
            return f'Cliccato "{label}".'
        except Exception as e:  # noqa: BLE001
            return f'Non ho trovato/cliccato "{label}": {e}'

    async def type_text(self, text: str, submit: bool = True) -> str:
        """Scrive nel campo gia' attivo (se ce n'e' uno) o altrimenti nel
        campo di testo/contenteditable piu' plausibile (l'ultimo visibile
        sulla pagina — su una UI a chat e' quasi sempre quello in basso),
        poi preme Invio se submit=True. page.keyboard.type() simula
        pressioni vere invece di impostare il valore via JS: funziona sia su
        input/textarea classici sia su editor contenteditable/rich-text
        (comuni nelle SPA moderne, Genie Code incluso presumibilmente)."""
        context = await self._ensure_context()
        if not context.pages:
            return "Nessuna pagina aperta su cui scrivere."
        page = context.pages[-1]
        forced_draft = submit and _is_draft_only_host(page.url)
        if forced_draft:
            submit = False
        try:
            active = await page.evaluate(
                "() => { const el = document.activeElement; "
                "if (!el) return ''; "
                "return el.tagName + ':' + (el.isContentEditable ? 'editable' : (el.type || '')); }"
            )
            already_focused = active.startswith(("TEXTAREA", "INPUT")) or active.endswith("editable")
            if not already_focused:
                await page.locator(_INPUT_SELECTOR).last.click(timeout=5000)
            await page.keyboard.type(text, delay=15)
            if submit:
                await page.keyboard.press("Enter")
            result = f'Scritto "{text}"{" e inviato" if submit else ""}.'
            if forced_draft:
                result += " Lasciato come bozza (mai invio automatico su Teams/Outlook): controllalo e invialo tu."
            return result
        except Exception as e:  # noqa: BLE001
            return f"Non sono riuscito a scrivere nella pagina: {e}"

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
            elif kind == "read":
                outcomes.append(await agent.read())
            elif kind == "click" and action.get("text"):
                outcomes.append(await agent.click(action["text"]))
            elif kind == "type" and action.get("text"):
                outcomes.append(await agent.type_text(action["text"], action.get("submit", True)))
        except Exception as e:  # noqa: BLE001
            outcomes.append(f"Errore browser: {e}")

    cleaned = BROWSER_BLOCK_RE.sub("", text).strip()
    if outcomes:
        cleaned = f"{cleaned}\n\n{' '.join(outcomes)}".strip()
    return cleaned
