"""
JARVIS — core condiviso tra i canali (Telegram, Web): stato, workspace, esecuzione Claude Code.

Due motori per il testo (voce ha il suo, core/claude_api.py::run_voice*):
- `_run_claude_api()` (default): API Anthropic diretta con tool reali
  (read_file/write_file/list_dir/run_command, appoggiati sulla whitelist
  gia' esistente di core/system_executor.py::SystemExecutor) — niente
  processo CLI da avviare, il floor di ~11-12s misurato con `claude -p`
  sparisce. Scelta esplicita di Alessandro (2026-09-15): accettato di
  ricostruire l'accesso a file/git perso passando dall'API pura, in
  cambio della latenza.
- `_run_claude_cli()` (invariato, `claude -p` reale): resta l'unico motore
  per il workspace "trading", che carica il server MCP TradingView —
  l'API diretta non ha un ponte locale pronto per quello stdio MCP.
  Anche un ripiego manuale (`JARVIS_TEXT_ENGINE=cli` in .env) se il motore
  API dovesse rivelarsi un problema nei primi giorni d'uso.
"""

import os
import json
import time
import base64
import asyncio
import threading
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from core import turso, brain, browser, databricks, mail_actions, persona, system_actions, vscode_actions, weather
from core.executor_singleton import executor as _system_executor
from core.voice import face_id

load_dotenv()

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
JARVIS_HOME = Path(os.getenv("JARVIS_HOME", Path(__file__).parent.parent)).resolve()
MAX_TURNS = os.getenv("JARVIS_MAX_TURNS", "40")
MODEL = os.getenv("JARVIS_MODEL", "")  # es. "opus" oppure vuoto = default (solo motore CLI)
# La voce vuole risposte brevi e rapide (persona: max due frasi) — un modello
# più leggero taglia parecchi secondi di latenza percepita rispetto al
# default. Testo/Telegram restano su JARVIS_MODEL (default = normale).
VOICE_MODEL = os.getenv("JARVIS_VOICE_MODEL", "haiku")
DATABRICKS_QAS_HOST = os.getenv("DATABRICKS_QAS_HOST", "")

# Motore per testo/Telegram/dashboard: "api" (default, vedi docstring sopra)
# o "cli" per tornare al comportamento precedente senza toccare codice.
TEXT_ENGINE = os.getenv("JARVIS_TEXT_ENGINE", "api")
API_MODEL_ALIASES = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5", "opus": "claude-opus-5"}
API_MODEL = API_MODEL_ALIASES.get(os.getenv("JARVIS_TEXT_MODEL", "sonnet"), os.getenv("JARVIS_TEXT_MODEL", "claude-sonnet-5"))
MAX_TOOL_TURNS = int(MAX_TURNS)
MAX_HISTORY_TURNS = 8  # coppie utente/assistente conservate in state.json per workspace
MAX_TOOL_RESULT_CHARS = 12000

# Prezzi noti (USD per milione di token) - solo per stimare il costo nei log,
# stessa tabella (valori) gia' in core/claude_api.py per il canale voce.
_PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}

STATE_FILE = JARVIS_HOME / "state.json"
TMP_DIR = JARVIS_HOME / ".tmp"

# Workspace = cartelle in cui Jarvis puo' lavorare. Personalizza qui.
WORKSPACES = {
    "jarvis": str(JARVIS_HOME),
    "aura": os.getenv("WS_AURA", str(JARVIS_HOME)),
    "whitesoul": os.getenv("WS_WHITESOUL", str(JARVIS_HOME)),
    "trading": os.getenv("WS_TRADING", str(JARVIS_HOME)),
    "isabela": os.getenv("WS_ISABELA", str(JARVIS_HOME)),
    "vino": os.getenv("WS_VINO", str(JARVIS_HOME)),
    # EnvironmentRouter, blocco B — solo il routing verso il repo/ambiente
    # Iveco (Databricks/Qlik/PySpark), richiesta esplicita di Alessandro
    # (2026-09-16): "solo routing Iveco", niente altri MCP server per ora.
    # Genie/dbSQL (core/databricks.py) restano disponibili SEMPRE, a
    # prescindere dal workspace attivo — questa voce serve solo per
    # read_file/write_file/run_command e per il second brain quando si
    # parla esplicitamente di lavoro Iveco.
    "iveco": os.getenv("WS_IVECO", str(JARVIS_HOME)),
}

# Riconoscimento automatico del progetto dal testo del task — richiesta
# esplicita di Alessandro (2026-09-16): non vuole piu' scegliere a mano il
# progetto dalle pill della dashboard ("non mi piace avere tutti quei
# contesti sopra"). Usato solo dalla dashboard web (core/web_bridge.py);
# il bot Telegram resta sul comando esplicito /ws (state["ws"]), non
# passa da qui. "jarvis" resta il default quando nessuna parola chiave
# matcha, stesso comportamento di prima quando la pill era su "jarvis".
_WORKSPACE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "aura": ("aura",),
    "whitesoul": ("white soul", "whitesoul", "white-soul"),
    "trading": ("tradeflow", "trading", "xau", "forex", "mt4", "mt5", "expert advisor", "backtest"),
    "isabela": ("isabela",),
    "vino": ("vinitalimport", "vino", "cantina", "bottigli"),
    "iveco": ("iveco", "databricks", "qlik", "unity catalog", "pyspark", "genie", "dbsql"),
}


def detect_workspace(prompt: str) -> str:
    low = prompt.lower()
    for ws, keywords in _WORKSPACE_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return ws
    return "jarvis"

SYSTEM = (
    "Sei JARVIS, assistente personale di Alessandro. Rivolgiti a lui con "
    "gentilezza e cortesia, sempre — mai freddo, mai sbrigativo. "
    "Rispondi in italiano. Frasi brevi, niente preamboli. "
    "Leggi sempre memory/profile.md e il file di progetto pertinente prima di agire, "
    "e segui un eventuale playbook pertinente in memory/playbooks/. "
    "A fine task aggiorna memory/log/<data>.md con: task, esito, cosa hai imparato. "
    "Se un task e' distruttivo o irreversibile, chiedi conferma prima. "
    "Confini assoluti, senza eccezioni: mai pubblicare su social o inviare messaggi "
    "a clienti senza conferma esplicita; mai eseguire ordini di trading reali (solo "
    "analisi, backtest, report); in git lavora sempre su branch, mai push diretto "
    "su main senza dirlo prima.\n\n"
    "Hai anche una memoria a lungo termine (second brain, nodi e relazioni) che ti "
    "viene fornita qui sotto come contesto, quando presente. Quando emerge un'idea, "
    "un fatto o una decisione duratura degna di essere ricordata in futuro (non il "
    "risultato banale di un task qualsiasi), aggiungi IN FONDO alla risposta un blocco:\n"
    "```brain\n"
    '{"nodes":[{"label":"...","summary":"...","tags":["..."]}],'
    '"edges":[{"source":"...","target":"...","relation":"..."}]}\n'
    "```\n"
    "Sii selettivo — non un nodo per ogni risposta. Il blocco viene rimosso prima di "
    "mostrare la risposta, quindi non commentarlo a parole.\n\n"
    "Se l'utente ti chiede di navigare un sito vero, cercare qualcosa e aprirlo, o "
    "guardare un video (non una domanda a cui sai già rispondere), aggiungi IN FONDO "
    "alla risposta un blocco:\n"
    "```browser\n"
    '{"action":"open","url":"..."}\n'
    "```\n"
    "oppure\n"
    "```browser\n"
    '{"action":"search","engine":"youtube","query":"...","open_first_result":true}\n'
    "```\n"
    '("engine" può essere "google" o "youtube"). Usalo solo quando serve davvero '
    "aprire un browser reale — non per domande generiche. Se l'utente chiede di "
    "aprire/navigare Databricks (senza specificare produzione), usa il blocco "
    '```browser``` con "action":"open" e l\'URL dell\'ambiente di test (QAS): '
    f'{DATABRICKS_QAS_HOST or "(non configurato)"}. Non hai un URL diretto per aprire '
    "una conversazione/notebook specifico. Puoi pero' leggere e interagire con "
    "qualunque pagina gia' aperta nel browser di JARVIS (mai il browser normale "
    "dell'utente, che non puoi toccare) con altri blocchi ```browser```:\n"
    '{"action":"read"} - testo visibile della pagina corrente (usalo PRIMA di '
    "cliccare/scrivere, per vedere davvero cosa c'e', invece di indovinare);\n"
    '{"action":"click","text":"..."} - clicca il primo elemento che contiene quel '
    "testo visibile (non un selettore CSS/XPath: descrivi cosa vuoi cliccare in "
    'linguaggio naturale, es. "Genie Code");\n'
    '{"action":"type","text":"...","submit":true} - scrive nel campo attivo (o nel '
    "campo di testo piu' plausibile della pagina) e preme Invio se submit e' true "
    "(default true, mettilo a false se non deve inviare subito).\n"
    'Per leggere davvero delle mail su Outlook Web (outlook.office.com), NON usare '
    '"read" (torna anche ribbon/cartelle/anteprime mischiati al contenuto — per '
    "questo la posta ha gia' un canale rapido dedicato che non passa nemmeno da te; "
    'se arrivi comunque qui e la pagina e\' gia\' aperta) usa invece:\n'
    '{"action":"read_mail","count":3} - apre in sequenza le prime N mail '
    "dell'elenco (default 3, max 5) e ne ritorna SOLO il corpo di ciascuna, gia' "
    "filtrato da bottoni/menu/cartelle. Poi fanne tu il riassunto nella risposta, "
    "non limitarti a incollare il testo grezzo.\n"
    "Con questi puoi aprire il pannello Genie Code (di solito un pulsante/icona con "
    "quel nome), leggere l'ultima risposta, scrivere una domanda e leggerne l'esito — "
    "ma leggi sempre la pagina prima di ogni azione, la UI reale la vedi solo cosi', "
    "non per certo dove sono gli elementi. Se un click/read fallisce (pagina non "
    "ancora caricata, elemento non trovato), dillo e non insistere all'infinito. Non "
    "hai NESSUN modo di "
    "accendere/controllare la webcam tu stesso, ne' esiste un sito o un URL locale "
    "(dashboard compresa, anche se gira su localhost) che la apra: se l'utente ti "
    "chiede di vedere/scattare qualcosa e non hai ricevuto nessuna immagine allegata "
    "a questo messaggio, dillo chiaramente (es. \"non ho ricevuto nessuna foto, "
    "Signore\") — non aprire mai un browser per cercare di rimediare. Stesso "
    "discorso per qualunque altro concetto locale (second brain, pannelli della "
    "dashboard): sono gestiti in locale, non sono siti web da navigare.\n\n"
    "Se l'utente chiede un'azione REALE sul suo PC Windows (aprire/chiudere "
    "un'applicazione, alzare/abbassare/mutare il volume, bloccare lo schermo, "
    "mostrare il desktop, fare uno screenshot, spegnere/riavviare/disconnettere "
    "il PC), aggiungi IN FONDO alla risposta un blocco:\n"
    "```system\n"
    '{"action":"open_app","name":"chrome"}\n'
    "```\n"
    'Altre "action" disponibili: "close_app" (con "name"), "volume" (con '
    '"direction": up/down/mute/unmute), "lock", "show_desktop", "screenshot", '
    '"power" (con "mode": shutdown/restart/logoff — spegnimento/riavvio/logout '
    "chiedono sempre conferma esplicita, non avviene subito). I comandi brevi e "
    "diretti vengono gia' gestiti prima di arrivare a te: se ricevi comunque una "
    "richiesta simile, è quasi certamente parte di una richiesta più composta — "
    "esegui comunque l'azione col blocco.\n\n"
    "Se l'utente chiede di interrogare Databricks Genie (analisi/domande sui "
    "dati Iveco), aggiungi IN FONDO alla risposta un blocco:\n"
    "```genie\n"
    '{"question":"..."}\n'
    "```\n"
    "Riformula la domanda in modo chiaro e autosufficiente (Genie non vede "
    "questa conversazione). Interroga SEMPRE E SOLO l'ambiente di test (QAS) — "
    "non esiste nessun modo per te di raggiungere l'ambiente di produzione: se "
    "l'utente lo chiede esplicitamente, digli di usare /genie_prd <domanda> su "
    "Telegram, che richiede una sua conferma separata.\n\n"
    "Se l'utente chiede di eseguire una query SQL vera su Databricks (non una "
    "domanda in linguaggio naturale — quella e' Genie sopra), aggiungi IN FONDO "
    "alla risposta un blocco:\n"
    "```dbsql\n"
    '{"sql":"SELECT ..."}\n'
    "```\n"
    "SOLO query di sola lettura (SELECT/SHOW/DESCRIBE/EXPLAIN), una per blocco — "
    "qualunque altra cosa (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/più istruzioni) "
    "viene comunque rifiutata dal codice, non sprecare un blocco per tentarci. "
    "SEMPRE E SOLO l'ambiente di test (QAS): per produzione l'utente deve usare "
    "/sql_prd <query> su Telegram, con conferma separata. Non esiste alcuna "
    "integrazione con \"Genie Code\" (l'assistente di coding dentro l'interfaccia "
    "Databricks) — verificato che non ha nessuna API esterna, è uno strumento "
    "solo per un umano dentro quella UI: se l'utente lo nomina, chiarisci questo "
    "invece di far finta di poterci accedere.\n\n"
    "Se ricevi un'immagine allegata che NON è la webcam (mostra invece Teams, "
    "Outlook, o una schermata del PC/Databricks), leggila e rispondi in base a "
    "cosa mostra.\n\n"
    "Per rispondere/scrivere una MAIL, aggiungi IN FONDO:\n"
    "```mail_draft\n"
    '{"to":"...","subject":"...","body":"..."}\n'
    "```\n"
    "Crea una bozza vera in Outlook (solo .Save(), mai .Send()) — dillo, non "
    "affermare mai di averla spedita.\n\n"
    "Per rispondere/scrivere su TEAMS, se la pagina e' gia' aperta/loggata nel "
    "browser di JARVIS (controlla con ```browser``` {\"action\":\"read\"} "
    "prima — altrimenti ripiega su una bozza a parole), scrivi con "
    "```browser``` {\"action\":\"type\",\"text\":\"...\",\"submit\":false}: il "
    "codice forza comunque submit=false su teams.microsoft.com/outlook.office.com, "
    "non partira' mai da solo. Non affermare mai di aver inviato/pubblicato "
    "qualcosa su Teams/Outlook.\n\n"
    "Per aprire un progetto in VS Code e/o far lavorare Claude Code su una "
    "modifica vera, aggiungi IN FONDO:\n"
    "```vscode\n"
    '{"project":"...","prompt":"..."}\n'
    "```\n"
    f'"project" SOLO tra: {", ".join(sorted(WORKSPACES))} (altrimenti dillo, '
    'non inventare il blocco). "prompt" facoltativo: omettilo per aprire solo '
    "VS Code. Con un prompt lanci una sessione VERA e autonoma di Claude Code "
    "(il CLI, non tu) in background — risultato su Telegram dopo, magari "
    "minuti dopo, mai nella tua risposta: di' che hai delegato, non che hai "
    "gia' scritto tu il codice.\n\n"
    "Hai accesso a strumenti reali per leggere/scrivere file ed eseguire comandi "
    "(read_file/write_file/list_dir/run_command) nel workspace corrente o in un "
    "altro progetto autorizzato — usali quando il task lo richiede davvero "
    "(leggere/modificare codice, controllare git, ecc.), non per domande a cui "
    "sai gia' rispondere. Un comando fuori dalla whitelist di sicurezza (es. "
    "`git push`) torna un token di conferma invece di eseguire: dillo chiaramente "
    "all'utente nella risposta (\"serve conferma: /confirm <token> su Telegram\"), "
    "non provare ad aggirarlo con un comando equivalente."
)

# --------------------------------------------------------------------------- state

state: dict = {}
_state_lock = asyncio.Lock()
CLAUDE_LOCK = asyncio.Lock()  # un solo `claude -p` alla volta, condiviso tra tutti i canali


def load_state() -> dict:
    if STATE_FILE.exists():
        loaded = json.loads(STATE_FILE.read_text())
        loaded.setdefault("sessions", {})
        loaded.setdefault("api_sessions", {})  # history del motore API, chiave separata apposta
        return loaded
    return {"ws": "jarvis", "sessions": {}, "api_sessions": {}}


def save_state(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, indent=2))


state = load_state()

# --------------------------------------------------------------------------- system prompt condiviso


async def _build_context_prefix(ws: str) -> str:
    """Data/ora + meteo + second brain — condiviso dai due motori testo (CLI/API)
    e concettualmente identico a core/claude_api.py::_build_system_prompt()
    per la voce (che pero' aggiunge anche la persona, qui mai)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    system_prompt = f"{SYSTEM}\n\nData e ora attuali: {now}."
    # In parallelo, non in sequenza: sono due chiamate di rete indipendenti
    # (Open-Meteo/ip-api.com, Turso) prima ancora di rispondere — in sequenza
    # si sommavano per intero al tempo di risposta percepito.
    weather_task = asyncio.create_task(asyncio.to_thread(weather.get_weather_line))
    brain_task = asyncio.create_task(asyncio.to_thread(brain.fetch_context, ws)) if turso.ENABLED else None
    weather_line = await weather_task
    if weather_line:
        system_prompt += f" Meteo attuale: {weather_line}."
    if brain_task:
        ctx = await brain_task
        if ctx:
            system_prompt = f"{system_prompt}\n\n{ctx}"
    return system_prompt


async def _run_post_processing(text: str, ws: str, original_prompt: str, channel: str) -> str:
    """Pipeline condivisa dopo la risposta finale di Claude, identica per i
    due motori testo e per la voce (core/claude_api.py replica lo stesso
    ordine): second brain -> log interazione -> browser -> databricks
    (genie/dbsql) -> system_actions. Pura estrazione/ripulitura di blocchi
    ```testuali``` — nessun tool reale coinvolto qui, per questo funziona
    identica indipendentemente da come e' stata generata la risposta."""
    if turso.ENABLED and text:
        text = await asyncio.to_thread(brain.extract_and_store, text, ws)
    if turso.ENABLED:
        # Fire-and-forget: e' un log di attivita', non deve aggiungere
        # tempo in coda a una risposta che l'utente sta gia' aspettando.
        threading.Thread(target=brain.log_interaction, args=(original_prompt, ws, channel), daemon=True).start()
    if text:
        text = await browser.extract_and_execute(text)
    if text:
        text = await mail_actions.extract_and_execute(text)
    if text:
        text = await vscode_actions.extract_and_execute(text)
    if text:
        text = await databricks.extract_and_execute(text)
    if text:
        text = await system_actions.extract_and_execute(text, _system_executor)
    return text


# --------------------------------------------------------------------------- motore API diretta (default)

TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Legge il contenuto testuale di un file nel workspace corrente o in un "
            "altro progetto autorizzato. Usalo prima di modificare un file, o quando "
            "l'utente chiede di leggere/controllare qualcosa di preciso."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Percorso assoluto, o relativo al workspace corrente"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Scrive/sovrascrive un file di testo con il contenuto indicato (crea le "
            "cartelle mancanti). Il contenuto deve essere il file COMPLETO — sovrascrive "
            "tutto quello che c'era prima, non e' un patch/diff."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "Elenca i file/cartelle dentro un percorso.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Esegue un comando PowerShell (es. git status/log/diff/branch/checkout/"
            "switch/merge/add/commit, o un cmdlet di sola lettura come "
            "Get-ChildItem/Get-Content) in una cartella di lavoro. Un comando fuori "
            "dalla whitelist di sicurezza (incluso git push, sempre) torna un token "
            "di conferma invece di eseguire — in quel caso dillo chiaramente "
            "all'utente nella risposta finale, non ripetere il comando ne' provare "
            "un'alternativa per aggirarlo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "description": "Cartella di lavoro — default: il workspace corrente"},
            },
            "required": ["command"],
        },
    },
]


def _resolve_in_workspace(path: str, cwd: str) -> str:
    p = Path(path)
    return str(p) if p.is_absolute() else str(Path(cwd) / p)


def _truncate_tool_result(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + f"\n… (troncato, {len(text)} caratteri totali)"


def _execute_tool(name: str, tool_input: dict, cwd: str) -> tuple[str, bool]:
    """Esegue un tool_use di Claude appoggiandosi a SystemExecutor (whitelist +
    conferma gia' esistenti, condivisi con /run di Telegram). Ritorna
    (testo per il tool_result, is_error) — mai solleva, un errore diventa
    sempre un tool_result con is_error=True cosi' Claude puo' reagire."""
    try:
        if name == "read_file":
            r = _system_executor.read_file(_resolve_in_workspace(tool_input["path"], cwd))
        elif name == "write_file":
            r = _system_executor.write_file(_resolve_in_workspace(tool_input["path"], cwd), tool_input["content"])
        elif name == "list_dir":
            r = _system_executor.list_dir(_resolve_in_workspace(tool_input.get("path", "."), cwd))
        elif name == "run_command":
            run_cwd = _resolve_in_workspace(tool_input["cwd"], cwd) if tool_input.get("cwd") else cwd
            r = _system_executor.run(tool_input["command"], run_cwd)
        else:
            return f"Tool sconosciuto: {name}", True
    except Exception as e:  # noqa: BLE001 — un tool rotto non deve far crashare il loop
        return f"Errore imprevisto eseguendo {name}: {e}", True

    if r.needs_confirmation:
        return (
            f'Azione fuori whitelist di sicurezza — serve una conferma esplicita '
            f'dell\'utente prima di eseguirla. Digli di rispondere "/confirm {r.token}" '
            f'su Telegram per confermarla, o "/deny {r.token}" per annullarla.',
            False,
        )
    if not r.ok:
        return _truncate_tool_result(r.stderr or "Errore sconosciuto."), True
    if name == "write_file":
        return "File scritto correttamente.", False
    return _truncate_tool_result(r.stdout or "(vuoto)"), False


def _decode_b64_image(image_b64: str) -> bytes:
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    return base64.b64decode(image_b64)


async def _build_user_content(prompt: str, image_b64: str | None) -> str | list[dict]:
    """Come core/claude_api.py::_build_messages() per la parte immagine —
    duplicato apposta invece di importarlo da li' (evita un ciclo di import,
    claude_api.py importa gia' SYSTEM da qui) e perche' il meccanismo e'
    diverso: qui l'immagine va in un content block "image" vero (vision),
    non riferita come path di file da un tool Read come faceva il motore CLI."""
    if not image_b64:
        return prompt

    raw = _decode_b64_image(image_b64)
    identity_line = ""
    try:
        import numpy as np
        import cv2

        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        name, _confidence = face_id.recognize(frame) if frame is not None else (None, -1.0)
        if name:
            identity_line = (
                f"Riconoscimento locale (webcam): la persona nella foto e' quasi "
                f"certamente {name.capitalize()} — puoi rivolgerti a lui per nome se "
                "ha senso nel contesto, senza bisogno di chiedere conferma.\n\n"
            )
    except Exception:
        pass  # riconoscimento best-effort: se fallisce si procede senza identita'

    text = (
        f"{identity_line}L'utente ti mostra questa immagine (webcam o schermo). "
        "Se nella foto indossa degli occhiali, commenta scherzosamente (una "
        "battuta breve, non seriosa) che con quegli occhiali sembra napoletano — "
        f"solo se ci sono davvero occhiali visibili, altrimenti non nominarlo.\n\n{prompt}"
    )
    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode("ascii")},
        },
        {"type": "text", "text": text},
    ]


_api_client: anthropic.AsyncAnthropic | None = None


def _get_api_client() -> anthropic.AsyncAnthropic:
    global _api_client
    if _api_client is None:
        _api_client = anthropic.AsyncAnthropic()
    return _api_client


def _trim_history(history: list[dict]) -> list[dict]:
    """Tiene solo le ultime MAX_HISTORY_TURNS coppie utente/assistente. Sicuro
    tagliare a coppie fisse perche' la history persistita qui e' SEMPRE testo
    pulito (mai un tool_result/tool_use grezzo) — vedi _run_claude_api."""
    return history[-(MAX_HISTORY_TURNS * 2):]


async def _run_claude_api(
    prompt: str, ws: str, cwd: str, image_b64: str | None, channel: str
) -> tuple[str, None, float]:
    """Motore di default per testo/Telegram/dashboard: API Anthropic diretta
    con tool reali (vedi TOOLS/_execute_tool sopra) invece del processo CLI.
    La history persistita in state.json e' solo testo pulito (mai i turni
    intermedi di tool_use/tool_result) — piu' leggera da rileggere/troncare,
    e Claude non ha comunque bisogno di rivedere il proprio ragionamento
    passato, solo l'esito conversazionale."""
    client = _get_api_client()
    system_prompt = await _build_context_prefix(ws)
    if channel == "voice":
        system_prompt = f"{system_prompt}\n\n{persona.PERSONA}"

    user_content = await _build_user_content(prompt, image_b64)
    history = _trim_history(list(state["api_sessions"].get(ws) or []))
    messages = [*history, {"role": "user", "content": user_content}]

    in_tokens = out_tokens = 0
    final_text = "(nessun output)"

    for _ in range(MAX_TOOL_TURNS):
        response = await client.messages.create(
            model=API_MODEL, max_tokens=8000, system=system_prompt, tools=TOOLS, messages=messages,
        )
        in_tokens += response.usage.input_tokens
        out_tokens += response.usage.output_tokens
        messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})

        if response.stop_reason != "tool_use":
            final_text = next((b.text for b in response.content if b.type == "text"), "(nessun output)")
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result_text, is_error = _execute_tool(block.name, block.input, cwd)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_text, "is_error": is_error}
            )
        messages.append({"role": "user", "content": tool_results})
    else:
        final_text = "Troppi passaggi per completare il task, mi fermo qui — riprova con una richiesta più mirata."

    final_text = await _run_post_processing(final_text, ws, prompt, channel)

    new_history = [*history, {"role": "user", "content": user_content}, {"role": "assistant", "content": final_text}]
    state["api_sessions"][ws] = _trim_history(new_history)
    save_state(state)

    in_price, out_price = _PRICING.get(API_MODEL, (0.0, 0.0))
    cost = (in_tokens * in_price + out_tokens * out_price) / 1_000_000
    return final_text, None, cost


# --------------------------------------------------------------------------- motore CLI (solo workspace "trading", o ripiego)


def _save_temp_image(image_b64: str) -> Path:
    TMP_DIR.mkdir(exist_ok=True)
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    path = TMP_DIR / f"cam-{int(time.time() * 1000)}.jpg"
    path.write_bytes(base64.b64decode(image_b64))
    return path


async def _run_claude_cli(
    prompt: str, ws: str, cwd: str, image_b64: str | None, channel: str
) -> tuple[str, str | None, float]:
    """Lancia claude -p nel workspace indicato. Ritorna (testo, session_id, costo).
    Invariato rispetto a prima dell'introduzione del motore API — resta l'unico
    percorso per "trading" (MCP TradingView) e il ripiego manuale via
    JARVIS_TEXT_ENGINE=cli."""
    sid = state["sessions"].get(ws)
    original_prompt = prompt  # per il log second-brain: prima che venga arricchito col testo webcam/identita'

    image_path = None
    if image_b64:
        try:
            image_path = await asyncio.to_thread(_save_temp_image, image_b64)

            identity_line = ""
            try:
                name, confidence = await asyncio.to_thread(face_id.recognize_file, image_path)
                if name:
                    identity_line = (
                        f"Riconoscimento locale (webcam): la persona nella foto e' quasi "
                        f"certamente {name.capitalize()} — puoi rivolgerti a lui per nome se "
                        "ha senso nel contesto, senza bisogno di chiedere conferma.\n\n"
                    )
            except Exception:
                pass  # riconoscimento best-effort: se fallisce si procede senza identita'

            prompt = (
                f"{identity_line}L'utente ti mostra questa immagine dalla webcam (usa il tuo "
                f"strumento di lettura per vederla): {image_path}\n\n"
                "Se nella foto indossa degli occhiali, commenta scherzosamente (una "
                "battuta breve, non seriosa) che con quegli occhiali sembra napoletano — "
                "solo se ci sono davvero occhiali visibili, altrimenti non nominarlo.\n\n"
                f"{prompt}"
            )
        except (ValueError, OSError):
            pass  # immagine corrotta: procedi solo col testo

    system_prompt = await _build_context_prefix(ws)
    if channel == "voice":
        system_prompt = f"{system_prompt}\n\n{persona.PERSONA}"

    cmd = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--append-system-prompt",
        system_prompt,
        "--max-turns",
        MAX_TURNS,
        "--permission-mode",
        "acceptEdits",
    ]
    if ws != "trading":
        # I server MCP configurati a livello globale (es. TradingView) si
        # connettono ad ogni avvio anche quando non servono, costando
        # diversi secondi extra per comando. Caricarli solo nel workspace
        # che li usa davvero dimezza il tempo di risposta altrove.
        cmd += ["--strict-mcp-config"]
    if os.getenv("JARVIS_CLI_BARE", "1") != "0":
        # --bare salta hook/LSP/plugin-sync/auto-memory/prefetch in background
        # e l'auto-discovery di CLAUDE.md di Claude Code stesso — tutta roba
        # che JARVIS non usa (ha la propria memoria in memory/ e second brain).
        # Richiede ANTHROPIC_API_KEY (gia' in .env per il canale voce): con
        # --bare l'autenticazione passa da abbonamento/OAuth a pagamento a
        # consumo sull'API key, anche per questo canale. Misurato dal vivo
        # (2026-07-16): costo per chiamata ~5-10x piu' basso (meno token di
        # contesto iniettati automaticamente), stessi strumenti (Read/Write/
        # Bash verificati funzionanti) e --resume compatibile; il tempo totale
        # non migliora in modo drammatico (il floor e' l'avvio del processo
        # CLI stesso, non toccato da questo flag). Togli JARVIS_CLI_BARE=0 in
        # .env per tornare al comportamento precedente.
        cmd += ["--bare"]
    model = VOICE_MODEL if channel == "voice" else MODEL
    if model:
        cmd += ["--model", model]
    if sid:
        cmd += ["--resume", sid]

    async with CLAUDE_LOCK:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()

    try:
        if proc.returncode != 0:
            # sessione corrotta / non trovata -> resetta e riprova pulito
            if sid:
                state["sessions"].pop(ws, None)
                save_state(state)
                return ("Sessione scaduta. Riprova.", None, 0.0)
            return (f"Errore claude:\n{err.decode(errors='replace')[:1500]}", None, 0.0)

        try:
            data = json.loads(out.decode(errors="replace"))
        except json.JSONDecodeError:
            return (out.decode(errors="replace")[:3800], None, 0.0)

        text = data.get("result") or "(nessun output)"
        new_sid = data.get("session_id")
        cost = float(data.get("total_cost_usd") or 0)

        if new_sid:
            state["sessions"][ws] = new_sid
            save_state(state)

        text = await _run_post_processing(text, ws, original_prompt, channel)

        return (text, new_sid, cost)
    finally:
        if image_path:
            try:
                image_path.unlink(missing_ok=True)
            except OSError:
                pass


# --------------------------------------------------------------------------- dispatcher pubblico


async def run_claude(
    prompt: str, ws: str | None = None, image_b64: str | None = None, channel: str = "text"
) -> tuple[str, str | None, float]:
    """Punto d'ingresso unico usato da bot.py/web_bridge.py — invariato nella
    firma. Sceglie il motore: API diretta di default, CLI per "trading"
    (MCP TradingView) o se JARVIS_TEXT_ENGINE=cli (ripiego manuale)."""
    ws = ws or state["ws"]
    cwd = WORKSPACES.get(ws, str(JARVIS_HOME))
    if ws == "trading" or TEXT_ENGINE == "cli":
        return await _run_claude_cli(prompt, ws, cwd, image_b64, channel)
    return await _run_claude_api(prompt, ws, cwd, image_b64, channel)
