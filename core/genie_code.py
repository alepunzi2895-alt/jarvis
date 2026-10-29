"""Chat Genie Code (assistente Databricks) di Alessandro, per il recap IVECO.

Richiesta di Alessandro del 2026-10-28: il recap deve sapere cosa ha fatto
durante la giornata anche con Genie Code (es. il deploy dei template degli
alert del 27/10, fatto tutto da una chat). Le chat sono notebook nascosti in
`/Users/<utente>/.conversations/`; i messaggi (richieste e risposte) non stanno
nelle celle esportabili ma nei comandi del notebook, letti con l'endpoint
interno `/notebook/<id>/command`. Risponde solo alla sessione dell'utente, non
al service principal: si legge dal browser JARVIS gia' loggato, come Teams.

Ogni chat viene salvata in markdown in `IVGAgent/work/genie_code/`, cosi'
anche le sessioni Claude Code di IVGAgent possono rileggerla. Sola lettura:
nessuna chat viene aperta nella UI, modificata o continuata.
"""
import asyncio
from datetime import datetime
import re

from core import agent_sessions
from core.ivg_dbx import IVG_ROOT

SAVE_DIR = IVG_ROOT / "work" / "genie_code"
_MAX_CHATS = 12
_READY_JS = "() => !!(window.settings && window.settings.csrfToken)"
# Solo i ruoli user/assistant: tool input/output (codice eseguito, risultati) e
# ragionamento interno restano fuori, come per le sessioni Claude Code.
_CHATS_JS = """async ({sinceMs, max}) => {
  const headers = {'X-CSRF-Token': window.settings.csrfToken};
  const get = async (url) => {
    const response = await fetch(url, {headers});
    if (!response.ok) throw new Error('HTTP ' + response.status + ' ' + url.split('?')[0]);
    return response.json();
  };
  const me = await get('/ajax-api/2.0/preview/scim/v2/Me');
  const base = '/Users/' + me.userName + '/.conversations';
  const listing = await get('/ajax-api/2.0/workspace/list?path=' + encodeURIComponent(base));
  const chats = (listing.objects || [])
    .filter((item) => item.object_type === 'NOTEBOOK' && (item.modified_at || 0) >= sinceMs)
    .sort((a, b) => b.modified_at - a.modified_at).slice(0, max);
  const out = [];
  for (const chat of chats) {
    const commands = await get('/notebook/' + chat.object_id + '/command');
    const messages = [];
    for (const command of [...commands].sort((a, b) => (a.position || 0) - (b.position || 0))) {
      let meta = {};
      try { meta = typeof command.metadata === 'string' ? JSON.parse(command.metadata) : (command.metadata || {}); } catch (e) {}
      if (meta.role !== 'user' && meta.role !== 'assistant') continue;
      const text = (command.command || '').replace(/^%md\\s*/, '')
        .replace(/__REASONING_START__[\\s\\S]*?(__REASONING_END__|$)/g, '').trim();
      if (text) messages.push({role: meta.role, text: text.slice(0, 20000)});
    }
    out.push({id: String(chat.object_id), modified: chat.modified_at, messages,
              title: chat.path.split('/').pop().replace(/^___DBCONVERSATION___\\(\\):\\s*/, '')});
  }
  return out;
}"""


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "chat"


def _stamp(ms) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def save(env: str, chat: dict) -> str:
    """Trascrizione markdown della chat; riscritta solo se cambiata. Ritorna il nome del file."""
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    path = SAVE_DIR / f"{env}-{chat['id']}-{_slug(chat['title'])}.md"
    lines = [f"# {chat['title']}", "",
             f"Genie Code, Databricks {env.upper()}. Ultima attivita': {_stamp(chat['modified'])}. "
             "Solo richieste e risposte, senza codice eseguito. Salvata da JARVIS.", ""]
    for message in chat["messages"]:
        # Token lunghi oscurati anche su disco: una chat puo' contenere un PAT incollato.
        lines += ["## " + ("Alessandro" if message["role"] == "user" else "Genie Code"), "",
                  agent_sessions._SECRET_RE.sub("[oscurato]", message["text"]), ""]
    text = "\n".join(lines)
    if not path.is_file() or path.read_text(encoding="utf-8", errors="replace") != text:
        path.write_text(text, encoding="utf-8")
    return path.name


def collect(since: datetime, loop) -> list[dict]:
    """Chat Genie Code attive nella finestra del recap, QAS e PRD, salvate su disco.
    Un ambiente non raggiungibile non ferma l'altro; entrambi giu' = errore."""
    if loop is None:
        raise RuntimeError("browser JARVIS non raggiungibile da questo processo")
    from core import databricks
    from core.browser import get_agent
    rows, errors = [], []
    hosts = {env: databricks._ENVIRONMENTS[env]["host"] for env in ("qas", "prd")}
    for env, host in ((env, host) for env, host in hosts.items() if host):
        future = asyncio.run_coroutine_threadsafe(get_agent().evaluate_on(
            host, _READY_JS, _CHATS_JS, {"sinceMs": since.timestamp() * 1000, "max": _MAX_CHATS}), loop)
        try:
            chats = future.result(timeout=180)
        except Exception as error:  # noqa: BLE001 — l'altro ambiente puo' rispondere
            future.cancel()
            errors.append(f"{env.upper()}: {type(error).__name__}")
            continue
        for chat in chats:
            prompts = [agent_sessions._clip(m["text"], 400) for m in chat["messages"] if m["role"] == "user"]
            answers = [m["text"] for m in chat["messages"] if m["role"] == "assistant"]
            rows.append(dict(env=env.upper(), title=chat["title"], last_activity=_stamp(chat["modified"]),
                             prompts=prompts[-15:], last_answer=agent_sessions._clip(answers[-1] if answers else "", 1200),
                             saved_as=save(env, chat)))
    if errors and len(errors) == sum(map(bool, hosts.values())):
        raise RuntimeError("; ".join(errors))
    if errors:
        rows.append(dict(note="Ambienti non letti: " + ", ".join(errors)))
    return rows


def draft_request(ticket: dict, mode: str, dashboard: str | None = None) -> str:
    """Testo per Genie Code. Solo bozza: nessuna chat viene aperta o inviata.
    mode 'new': da zero. mode 'existing': estende una dashboard gia' esistente (nome obbligatorio)."""
    if mode == "existing":
        if not (dashboard or "").strip():
            raise ValueError("Per una dashboard esistente serve il nome.")
        where = f"Estendi la dashboard esistente '{dashboard.strip()}'. Non crearne una nuova."
    elif mode == "new":
        where = "Crea da zero. Nessuna dashboard di riferimento."
    else:
        raise ValueError("mode deve essere 'new' o 'existing'.")
    return "\n".join([
        f"Ticket {ticket['number']}: {ticket['short_description']}",
        where,
        "Richiesta dal ticket:",
        ticket["description"][:1500] or "(descrizione vuota)",
        "Prima di modificare qualcosa: elenca il piano e aspetta conferma.",
    ])
