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

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
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
_DRAFT_ONLY_HOSTS = ("teams.microsoft.com", "teams.cloud.microsoft", "outlook.office.com",
                     "outlook.office365.com", "outlook.live.com", "outlook.cloud.microsoft")

# Sul PC aziendale Teams e Outlook passano dal proxy Defender for Cloud Apps,
# che aggiunge ".mcas.ms" all'host (teams.cloud.microsoft.mcas.ms): senza
# toglierlo il blocco draft-only sopra non scattava sull'URL reale (2026-10-21).
_MCAS_SUFFIX = ".mcas.ms"


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removesuffix(_MCAS_SUFFIX)


def _is_draft_only_host(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith(f".{h}") for h in _DRAFT_ONLY_HOSTS)


# "leggere Outlook nel browser deve filtrare tutti i bottoni ecc e leggere
# solo le mail aprendole" (Alessandro, 2026-09-16): read() con inner_text("body")
# su Outlook Web dava un unico muro di testo — ribbon, albero cartelle,
# anteprime dell'elenco messaggi E il corpo della mail aperta tutti
# concatenati, che poi finiva letto ad alta voce parola per parola (bug
# osservato dal vivo: logs/bot.log del 2026-09-16 mostra JARVIS che legge
# "Crea nuovo messaggio"/"Sposta in cartella"/nomi di cartelle come se
# fossero contenuto vero). Fix: due ruoli ARIA STANDARD, indipendenti dalla
# lingua dell'interfaccia (a differenza degli aria-label, che sono
# localizzati) — role="option" per le righe dell'elenco messaggi,
# role="document" per il riquadro di lettura della mail aperta. Ribbon e
# albero cartelle sono sempre role="button"/"treeitem", mai inclusi in
# nessuno dei due, quindi il filtro e' strutturale, non un elenco di parole
# da escludere.
_OWA_HOSTS = ("outlook.office.com", "outlook.office365.com", "outlook.live.com", "outlook.cloud.microsoft")
_MAX_MAIL_ITEMS = 5


def _is_owa_host(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith(f".{h}") for h in _OWA_HOSTS)


# App a pagina singola da non aprire mai due volte nello stesso profilo.
# 2026-10-27, "dopo un po' Teams va in palla o mi chiede una nuova apertura":
# ogni "Collega Teams", "guarda Teams" e recap apriva una scheda nuova, cioe'
# un'altra istanza completa di Teams sulla stessa sessione. Ora si riusa la
# scheda gia' aperta, anche se l'host e' cambiato con il redirect
# (teams.microsoft.com -> teams.cloud.microsoft.mcas.ms).
_SITE_FAMILIES = {
    "teams": ("teams.microsoft.com", "teams.cloud.microsoft", "teams.live.com"),
    "outlook": _OWA_HOSTS,
}


def _site_family(url: str) -> str | None:
    host = _host(url)
    for family, hosts in _SITE_FAMILIES.items():
        if any(host == h or host.endswith(f".{h}") for h in hosts):
            return family
    return None


def _same_target(requested: str, current: str) -> bool:
    family = _site_family(requested)
    if family:
        return family == _site_family(current)
    return requested.rstrip("/") == current.rstrip("/")


def _needs_login(url: str) -> bool:
    """Pagina di accesso Microsoft o del proxy Defender for Cloud Apps."""
    host = (urlparse(url).hostname or "").lower()
    return host.startswith("login.") or ".access.mcas.ms" in host


# "Selezionare un account" di login.microsoftonline.com: la sessione Microsoft
# del profilo JARVIS non sopravvive al riavvio del browser (cookie di sessione)
# e a ogni avvio Microsoft chiede quale account usare, gia' "Accesso eseguito".
# Verificato dal vivo il 2026-10-27: un clic sull'unico account completa
# l'accesso senza password. Con piu' account non si sceglie a caso.
_ACCOUNT_TILE = "[role=button][data-test-id*='@']:not([data-test-id$='-menu-dots'])"


async def _pick_signed_in_account(page) -> bool:
    """True se ha cliccato l'unico account gia' collegato nella pagina di accesso."""
    try:
        tiles = page.locator(_ACCOUNT_TILE)
        if not _needs_login(page.url) or await tiles.count() != 1:
            return False
        await tiles.first.click(timeout=5000)
        return True
    except Exception:  # noqa: BLE001 — pagina di accesso diversa: decide il chiamante
        return False


async def wait_ready(page, ready: str, timeout_ms: int = 45000) -> None:
    """Attende `ready` visibile fuori dalle pagine di accesso, scegliendo
    l'account se Microsoft lo chiede. Verificato dal vivo il 2026-10-27: anche
    la pagina di login ha un [role=main], e dopo l'accesso Outlook Web passa
    ancora da login.microsoftonline.com a *.mcas.ms (contesto JS distrutto):
    il selettore da solo non basta. PermissionError se l'accesso non riesce."""
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    picked = False
    while True:
        if not _needs_login(page.url):
            try:
                if await page.locator(ready).first.is_visible():
                    return
            except Exception:  # noqa: BLE001 — navigazione in corso
                pass
        elif not picked:
            picked = await _pick_signed_in_account(page)
        if asyncio.get_running_loop().time() > deadline:
            if _needs_login(page.url):
                raise PermissionError("accesso Microsoft scaduto nel browser JARVIS")
            raise TimeoutError(f"{ready} non comparso in {timeout_ms} ms")
        await asyncio.sleep(0.5)


# Lista chat di Teams per il recap del daily (2026-10-21). Righe e campi
# letti per id/attributo strutturale, non per testo localizzato: verificato
# dal vivo sul profilo JARVIS (Teams v2 via proxy mcas.ms) — ogni riga e'
# un treeitem data-item-type="chat" con titolo, anteprima e <time datetime>
# ISO in UTC; "non letta" e' un id in aria-labelledby. Il tipo di chat
# (OneOnOne/Group/Meeting/Bot/SelfChat) e' in data-fui-tree-item-value.
_TEAMS_CHAT_ROW = "[role=treeitem][data-item-type=chat]"
_TEAMS_CHAT_NAV = "[data-tid=app-bar-wrapper] button[aria-label^='Chat']"
_TEAMS_CHATS_JS = """() => [...document.querySelectorAll('[role=treeitem][data-item-type=chat]')].map(item => {
  const pick = prefix => item.querySelector(`[id^="${prefix}"]`);
  const [kind, id] = (item.getAttribute('data-fui-tree-item-value') || '').split('/').pop().split('|');
  return {
    id: id || '', kind: kind || '',
    title: pick('title-chat-list-item_')?.innerText || '',
    preview: pick('message-preview-chat-list-item_')?.innerText || '',
    at: item.querySelector('time')?.getAttribute('datetime') || '',
    unread: (item.getAttribute('aria-labelledby') || '').includes('chat_list_unread_text'),
  };
})"""


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
        # Scheda su cui agiscono read/click/type/screenshot: l'ultima aperta o
        # riportata in primo piano. Con il riuso delle schede l'ultima creata
        # (context.pages[-1]) non e' piu' per forza quella giusta.
        self._current = None

    def _active_page(self, context):
        page = self._current
        if page is not None and page in context.pages and not page.is_closed():
            return page
        return context.pages[-1]

    def _find_page(self, context, url: str):
        for page in reversed(context.pages):
            if not page.is_closed() and _same_target(url, page.url):
                return page
        return None

    async def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            self._playwright = await async_playwright().start()
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, viewport=None
            )
            # Un dialogo JS (alert/confirm/prompt — es. un banner cookie che
            # lo usa invece di un modal DOM) blocca la pagina finche'
            # qualcosa non lo chiude, e Playwright non lo fa da solo: senza
            # un handler ogni await successivo su quella pagina resta in
            # attesa per sempre. Su TUTTE le pagine del contesto (anche
            # quelle aperte da un click, non solo quelle create da noi) —
            # candidato principale del blocco totale del poller osservato
            # dal vivo il 2026-09-16 ("apri chrome e metti Battiato su
            # YouTube" ha fermato l'intera coda, non solo quel comando).
            # Vedi anche core/web_bridge.py::RUN_CLAUDE_TIMEOUT_SEC, difesa
            # complementare per qualunque altra causa dello stesso sintomo.
            self._context.on("page", lambda page: page.on("dialog", self._auto_dismiss_dialog))
            self._context.on("page", self._track_page)
        return self._context

    def _track_page(self, page) -> None:
        # Una scheda nuova (anche aperta da un link) diventa quella attiva,
        # come prima con context.pages[-1].
        self._current = page

    @staticmethod
    def _auto_dismiss_dialog(dialog) -> None:
        asyncio.ensure_future(dialog.dismiss())

    async def _reset(self) -> None:
        """Il contesto/browser puo' essere stato chiuso dall'esterno (finestra
        chiusa a mano, crash) senza che self._context lo sappia — si riparte
        da zero invece di restare bloccati su un riferimento morto."""
        self._context = None
        self._current = None
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

    @asynccontextmanager
    async def service_page(self, url: str, ready: str, timeout_ms: int = 45000):
        """Scheda di servizio per letture automatiche (Outlook Web come piano
        B): mai in primo piano, chiusa alla fine, la scheda attiva resta
        quella di prima. PermissionError se il sito chiede di nuovo l'accesso."""
        previous = self._current
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await wait_ready(page, ready, timeout_ms)
            yield page
        finally:
            await page.close()
            self._current = previous

    def is_open(self, url: str) -> bool:
        return self._context is not None and self._find_page(self._context, url) is not None

    async def open(self, url: str, foreground: bool = True) -> str:
        """`foreground=False`: apertura automatica, la scheda attiva e il focus restano come prima."""
        if (urlparse(url).hostname or "") in _LOCAL_HOSTS:
            return (
                "Non apro un browser per un indirizzo locale: dashboard, second brain e "
                "webcam sono gestiti in locale, non sono siti da navigare."
            )
        page = self._find_page(self._context, url) if self._context else None
        if page is not None:
            if not foreground:
                return f"{url} era gia' aperto."
            await page.bring_to_front()
            self._current = page
            _bring_browser_to_foreground()
            return f"{url} era gia' aperto: riportato in primo piano."
        previous = self._current
        page = await self._new_page()
        await page.goto(url, wait_until="domcontentloaded")
        if foreground:
            self._current = page
            _bring_browser_to_foreground()
        else:
            self._current = previous if previous is not None and not previous.is_closed() else page
        return f"Aperto {url}."

    async def search(self, engine: str, query: str, open_first_result: bool = True) -> str:
        if engine not in SEARCH_URLS:
            return f'Motore "{engine}" non supportato (solo google/youtube).'
        page = await self._new_page()
        url = SEARCH_URLS[engine].format(query=query.replace(" ", "+"))
        await page.goto(url, wait_until="domcontentloaded")
        self._current = page
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
        senza dover interpretare uno screenshot per ogni domanda. Su Outlook
        Web usa la lettura mirata (_read_scoped) invece del body intero —
        stesso filtro di read_emails(), qui applicato anche a un click/read
        manuale fatto da Claude passo-passo."""
        context = await self._ensure_context()
        if not context.pages:
            return "Nessuna pagina aperta nel browser di JARVIS."
        page = self._active_page(context)
        try:
            text = await self._read_scoped(page) if _is_owa_host(page.url) else ""
            if not text:
                text = await page.inner_text("body")
        except Exception as e:  # noqa: BLE001
            return f"Impossibile leggere la pagina: {e}"
        return _clean_page_text(text) or "(pagina vuota o senza testo visibile)"

    async def _read_scoped(self, page) -> str:
        """Riquadro di lettura (role="document") se una mail e' aperta,
        altrimenti l'elenco messaggi (role="option") — mai il body intero.
        Stringa vuota se nessuno dei due e' presente (pagina non ancora
        caricata): il chiamante ripiega su inner_text("body")."""
        try:
            doc = page.get_by_role("document")
            if await doc.count() > 0:
                text = (await doc.first.inner_text()).strip()
                if text:
                    return text
        except Exception:
            pass
        try:
            options = page.get_by_role("option")
            n = await options.count()
            if n:
                items = [
                    (await options.nth(i).inner_text()).strip()
                    for i in range(min(n, _MAX_MAIL_ITEMS * 3))
                ]
                return "\n---\n".join(i for i in items if i)
        except Exception:
            pass
        return ""

    async def read_emails(self, count: int = 3) -> str:
        """Apre in sequenza le prime `count` righe dell'elenco messaggi
        (Outlook Web) e ne legge SOLO il riquadro di lettura di ciascuna —
        Claude riceve il testo pulito di ogni mail e ne fa il riassunto
        nella sua risposta, questo metodo non riassume da solo (stesso
        principio di read(): dati grezzi puliti, non un'interpretazione)."""
        context = await self._ensure_context()
        if not context.pages:
            return "Nessuna pagina aperta nel browser di JARVIS."
        page = self._active_page(context)
        if not _is_owa_host(page.url):
            return (
                'Non sono su Outlook Web — apri prima "outlook.office.com" '
                'con ```browser``` {"action":"open"}.'
            )

        count = max(1, min(count, _MAX_MAIL_ITEMS))
        try:
            rows = page.get_by_role("option")
            total = await rows.count()
        except Exception as e:  # noqa: BLE001
            return f"Impossibile leggere l'elenco messaggi: {e}"
        if total == 0:
            return "Nessuna mail nell'elenco visibile."

        summaries: list[str] = []
        for i in range(min(count, total)):
            try:
                await rows.nth(i).click(timeout=5000)
                await page.wait_for_timeout(800)  # tempo per il caricamento del riquadro di lettura
                body = await self._read_scoped(page)
                summaries.append(
                    f"Mail {i + 1}:\n{_clean_page_text(body)}"
                    if body else f"Mail {i + 1}: corpo non leggibile (non ancora caricato)."
                )
            except Exception as e:  # noqa: BLE001 — una mail non apribile non deve fermare le altre
                summaries.append(f"Mail {i + 1}: non apribile ({e}).")
        _bring_browser_to_foreground()
        return "\n\n".join(summaries)

    async def read_teams_chats(self, url: str) -> list[dict]:
        """Righe della lista chat di Teams (titolo, tipo, anteprima
        dell'ultimo messaggio, ora, non letta) dal profilo gia' loggato.
        Solo la lista, mai una chat aperta: aprirla la segnerebbe come letta.
        Se Teams e' gia' aperto legge quella scheda, senza ricaricarla: una
        seconda istanza nello stesso profilo destabilizza Teams. Altrimenti
        scheda propria chiusa alla fine. Mai primo piano: gira anche alle
        09:30 senza nessuno davanti al PC."""
        existing = self._find_page(self._context, url) if self._context else None
        previous = self._current
        page = existing or await self._new_page()
        try:
            if existing is None:
                await page.goto(url, wait_until="domcontentloaded")
            rows = page.locator(_TEAMS_CHAT_ROW)
            try:
                await page.locator(f"{_TEAMS_CHAT_ROW}, {_ACCOUNT_TILE}").first.wait_for(timeout=45000)
                if await _pick_signed_in_account(page):
                    await rows.first.wait_for(timeout=45000)
                else:
                    await rows.first.wait_for(timeout=1000)
            except Exception:
                if _needs_login(page.url):
                    raise PermissionError("login Teams scaduto: riaprilo dai Collegamenti")
                # Teams riapre l'ultima app usata: se non e' Chat, la seleziona.
                await page.locator(_TEAMS_CHAT_NAV).first.click(timeout=5000)
                await rows.first.wait_for(timeout=20000)
            return await page.evaluate(_TEAMS_CHATS_JS)
        finally:
            if existing is None:
                await page.close()
                self._current = previous

    async def evaluate_on(self, url: str, ready_js: str, script: str, arg=None, timeout_ms: int = 60000):
        """Esegue `script` (funzione JS) in una pagina del sito di `url`, con la
        sessione del profilo JARVIS: le API interne di Databricks e ServiceNow
        rispondono solo alla sessione dell'utente (token CSRF in pagina), non al
        service principal. Riusa una scheda gia' aperta su quel sito senza
        ricaricarla; altrimenti scheda propria, mai in primo piano, chiusa alla
        fine. `ready_js` e' vero quando la pagina e' loggata e pronta."""
        host = urlparse(url).hostname
        context = await self._ensure_context()
        existing = next((p for p in reversed(context.pages)
                         if not p.is_closed() and urlparse(p.url).hostname == host), None)
        previous = self._current
        page = existing or await self._new_page()
        try:
            if existing is None:
                await page.goto(url, wait_until="domcontentloaded")
            deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
            picked = False
            while True:
                if _needs_login(page.url):
                    picked = picked or await _pick_signed_in_account(page)
                else:
                    try:
                        if await page.evaluate(ready_js):
                            break
                    except Exception:  # noqa: BLE001 — navigazione in corso
                        pass
                if asyncio.get_running_loop().time() > deadline:
                    if _needs_login(page.url):
                        raise PermissionError(f"accesso a {host} scaduto nel browser JARVIS: riaprilo dai Collegamenti")
                    raise TimeoutError(f"{host} non pronto in {timeout_ms} ms")
                await asyncio.sleep(0.5)
            return await page.evaluate(script, arg)
        finally:
            if existing is None:
                await page.close()
                self._current = previous

    async def click(self, label: str) -> str:
        """Clicca il primo elemento visibile che contiene il testo dato
        (non un selettore CSS/XPath — vedi nota sul vocabolario limitato)."""
        context = await self._ensure_context()
        if not context.pages:
            return "Nessuna pagina aperta da cui cliccare."
        page = self._active_page(context)
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
        page = self._active_page(context)
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

    async def screenshot(self, scoped: bool = False) -> bytes:
        """`scoped=True` (Teams, 2026-09-16: "filtra tutto il resto che non
        serve, vedi solo le chat e i messaggi") prova a fotografare solo la
        regione ARIA "main" della pagina invece dell'intera finestra — su
        una SPA con un vero landmark main (rail/nav laterali fuori da
        <main>) esclude gia' molto rumore senza bisogno di sapere la
        struttura DOM esatta di ogni sito. Ripiega sull'intera pagina se il
        landmark non c'e' o la cattura scoped fallisce — MAI un errore
        visibile per questo, e' solo un tentativo di inquadratura migliore."""
        context = await self._ensure_context()
        try:
            if not context.pages:
                return b""
            page = self._active_page(context)
            if scoped:
                try:
                    main = page.get_by_role("main")
                    if await main.count() > 0:
                        return await main.first.screenshot()
                except Exception:
                    pass
            return await page.screenshot()
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
            elif kind == "read_mail":
                outcomes.append(await agent.read_emails(action.get("count", 3)))
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
