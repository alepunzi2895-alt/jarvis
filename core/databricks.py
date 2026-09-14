"""
JARVIS — Databricks (Iveco): OAuth M2M (service principal) + Genie
Conversation API (docs.databricks.com/aws/en/genie/conversation-api) +
SQL Statement Execution API (docs.databricks.com/api/workspace/statementexecution).

"Genie Code" (l'assistente di coding dentro l'interfaccia Databricks,
ex Databricks Assistant) NON ha nessuna API esterna documentata — e'
strettamente un'esperienza dentro la UI, per un umano. Verificato sulla
doc ufficiale 2026-09-14, non e' quindi automatizzabile da qui. Quello
che si avvicina di piu' a "scrivere comandi e leggere risultati" in modo
sicuro e verificabile e' la Statement Execution API sotto — query SQL
vere, eseguite via codice nostro (non un secondo agente autonomo).

QAS e' l'unico ambiente che Claude puo' raggiungere da solo, sia per Genie
(blocco ```genie```) sia per SQL (blocco ```dbsql```, SOLA LETTURA -
SELECT/SHOW/DESCRIBE/EXPLAIN, verificato a codice prima di mandare
qualunque cosa a Databricks). PRD (produzione) NON e' mai raggiungibile
da quei percorsi automatici per scelta esplicita di sicurezza: richiede
i comandi dedicati /genie_prd o /sql_prd su Telegram, che passano
comunque dalla stessa conferma /confirm-/deny gia' usata da
SystemExecutor per le azioni rischiose — credenziali di produzione, non
ci si va per tentativi ne' per decisione autonoma di Claude.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid

import requests

GENIE_BLOCK_RE = re.compile(r"```genie\s*\n(.*?)\n```", re.DOTALL)
SQL_BLOCK_RE = re.compile(r"```dbsql\s*\n(.*?)\n```", re.DOTALL)

_TIMEOUT = 30
_POLL_INTERVAL = 2.0
_POLL_MAX_SECONDS = 300  # Genie/query pesanti possono impiegare qualche minuto (linea guida Databricks)
_SQL_WAIT_TIMEOUT = "30s"  # sotto il tetto di 50s dell'API, margine per il round-trip HTTP stesso
_SQL_ROW_LIMIT = 100

_TERMINAL_OK = {"COMPLETED"}
_TERMINAL_FAIL = {"FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}
_SQL_TERMINAL_OK = {"SUCCEEDED"}
_SQL_TERMINAL_FAIL = {"FAILED", "CANCELED", "CLOSED"}
_SQL_PENDING = {"PENDING", "RUNNING"}

# Whitelist, non blacklist: solo query che iniziano con una di queste parole
# (dopo eventuali commenti/righe vuote) sono considerate sola lettura — stessa
# filosofia a vocabolario limitato di core/browser.py. Un elenco di parole
# VIETATE sarebbe piu' facile da aggirare (es. un DELETE dentro un commento
# annidato, un secondo statement dopo un ';').
_READ_ONLY_SQL_RE = re.compile(r"^\s*(--[^\n]*\n\s*)*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN|WITH)\b", re.IGNORECASE)

_ENVIRONMENTS = {
    "qas": {
        "host": os.getenv("DATABRICKS_QAS_HOST", "").rstrip("/"),
        "client_id": os.getenv("DATABRICKS_QAS_CLIENT_ID", ""),
        "client_secret": os.getenv("DATABRICKS_QAS_CLIENT_SECRET", ""),
        "space_id": os.getenv("DATABRICKS_QAS_GENIE_SPACE_ID", ""),
        "warehouse_id": os.getenv("DATABRICKS_QAS_WAREHOUSE_ID", ""),
    },
    "prd": {
        "host": os.getenv("DATABRICKS_PRD_HOST", "").rstrip("/"),
        "client_id": os.getenv("DATABRICKS_PRD_CLIENT_ID", ""),
        "client_secret": os.getenv("DATABRICKS_PRD_CLIENT_SECRET", ""),
        "space_id": os.getenv("DATABRICKS_PRD_GENIE_SPACE_ID", ""),
        "warehouse_id": os.getenv("DATABRICKS_PRD_WAREHOUSE_ID", ""),
    },
}

_token_cache: dict[str, tuple[str, float]] = {}  # env -> (token, scadenza_epoch)
_pending: dict[str, tuple[str, str]] = {}  # token /confirm -> (kind: "genie"|"sql", payload) in sospeso per PRD


class GenieError(Exception):
    pass


def _env_config(env: str) -> dict:
    cfg = _ENVIRONMENTS.get(env)
    if not cfg or not cfg["host"] or not cfg["client_id"] or not cfg["client_secret"]:
        raise GenieError(f'Ambiente Databricks "{env}" non configurato in .env.')
    return cfg


def _get_token(env: str) -> str:
    cached = _token_cache.get(env)
    if cached and cached[1] > time.time() + 30:
        return cached[0]
    cfg = _env_config(env)
    resp = requests.post(
        f"{cfg['host']}/oidc/v1/token",
        auth=(cfg["client_id"], cfg["client_secret"]),
        data={"grant_type": "client_credentials", "scope": "all-apis"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    _token_cache[env] = (token, time.time() + float(data.get("expires_in", 3600)))
    return token


def _poll_message(host: str, headers: dict, space_id: str, conversation_id: str, message_id: str) -> dict:
    deadline = time.time() + _POLL_MAX_SECONDS
    delay = _POLL_INTERVAL
    url = f"{host}/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}"
    while True:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        message = resp.json()
        status = message.get("status")
        if status in _TERMINAL_OK:
            return message
        if status in _TERMINAL_FAIL:
            raise GenieError(f"Genie ha risposto con stato {status}.")
        if time.time() > deadline:
            raise GenieError("Genie non ha risposto entro 5 minuti.")
        time.sleep(delay)
        delay = min(delay * 1.5, 10.0)  # backoff esponenziale, tetto 10s (linea guida Databricks: 1-5s -> fino a 1min)


def _extract_answer(message: dict) -> str:
    parts = []
    for att in message.get("attachments", []):
        text = (att.get("text") or {}).get("content")
        if text:
            parts.append(text)
        query = (att.get("query") or {}).get("query")
        if query:
            parts.append(f"(SQL eseguita: {query})")
    return "\n\n".join(parts) if parts else "Genie non ha prodotto una risposta testuale per questa domanda."


def ask_genie(question: str, env: str = "qas") -> str:
    """Fa una domanda a Databricks Genie, ritorna la risposta testuale.
    Il chiamante e' responsabile di decidere se 'env' puo' essere 'prd' —
    questa funzione non ha una propria whitelist, e' la sola ask_genie_qas()
    (usata dal blocco automatico) a impedire 'prd' strutturalmente."""
    cfg = _env_config(env)
    space_id = cfg["space_id"]
    if not space_id:
        raise GenieError(
            f'Nessun Genie Space configurato per l\'ambiente "{env}" '
            f"(DATABRICKS_{env.upper()}_GENIE_SPACE_ID in .env)."
        )
    host = cfg["host"]
    headers = {"Authorization": f"Bearer {_get_token(env)}"}

    resp = requests.post(
        f"{host}/api/2.0/genie/spaces/{space_id}/start-conversation",
        headers=headers,
        json={"content": question},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    conv = resp.json()

    message = _poll_message(host, headers, space_id, conv["conversation_id"], conv["message_id"])
    return _extract_answer(message)


def ask_genie_qas(question: str) -> str:
    """Unico entry point raggiungibile dal blocco ```genie``` automatico —
    'env' e' fisso a qas, non e' un parametro che il testo estratto da
    Claude puo' influenzare in alcun modo."""
    return ask_genie(question, env="qas")


def stage_prd_confirmation(kind: str, payload: str) -> str:
    """Mette in sospeso un'azione (kind: 'genie' o 'sql') per l'ambiente PRD,
    ritorna il token da confermare — stesso pattern (token corto, dizionario
    in memoria) di SystemExecutor._stage_confirmation(), volutamente
    separato invece di condiviso: PRD Databricks non ha nulla a che fare
    con le azioni di sistema che SystemExecutor gestisce."""
    token = uuid.uuid4().hex[:8]
    _pending[token] = (kind, payload)
    return token


def confirm_prd(token: str) -> str:
    pending = _pending.pop(token, None)
    if pending is None:
        raise GenieError("Token non valido o scaduto.")
    kind, payload = pending
    if kind == "genie":
        return ask_genie(payload, env="prd")
    if kind == "sql":
        return run_sql(payload, env="prd")
    raise GenieError(f'Tipo di conferma sconosciuto: "{kind}".')


def deny_prd(token: str) -> bool:
    return _pending.pop(token, None) is not None


def _is_read_only_sql(sql: str) -> bool:
    stripped = sql.strip()
    if not _READ_ONLY_SQL_RE.match(stripped):
        return False
    body = stripped[:-1].rstrip() if stripped.endswith(";") else stripped
    return ";" not in body  # una sola istruzione: niente statement nascosti dopo il primo


class SqlError(Exception):
    pass


def list_warehouses(env: str = "qas") -> list[dict]:
    cfg = _env_config(env)
    headers = {"Authorization": f"Bearer {_get_token(env)}"}
    resp = requests.get(f"{cfg['host']}/api/2.0/sql/warehouses", headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("warehouses", [])


def _poll_statement(host: str, headers: dict, statement_id: str, data: dict) -> dict:
    deadline = time.time() + _POLL_MAX_SECONDS
    delay = _POLL_INTERVAL
    while data.get("status", {}).get("state") in _SQL_PENDING:
        if time.time() > deadline:
            raise SqlError("Query non completata entro 5 minuti.")
        time.sleep(delay)
        delay = min(delay * 1.5, 10.0)
        resp = requests.get(f"{host}/api/2.0/sql/statements/{statement_id}", headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    state = data.get("status", {}).get("state")
    if state in _SQL_TERMINAL_FAIL:
        err = (data.get("status", {}).get("error") or {}).get("message", state)
        raise SqlError(f"Query fallita: {err}")
    return data


def _format_sql_result(data: dict) -> str:
    manifest = data.get("manifest", {})
    columns = [c["name"] for c in manifest.get("schema", {}).get("columns", [])]
    rows = data.get("result", {}).get("data_array", [])
    if not rows:
        return "Nessuna riga restituita."
    shown = rows[:50]
    lines = [" | ".join(columns)] if columns else []
    lines += [" | ".join("" if v is None else str(v) for v in row) for row in shown]
    total = manifest.get("total_row_count", len(shown))
    if total > len(shown):
        lines.append(f"({total} righe totali, mostrate {len(shown)})")
    return "\n".join(lines)


def run_sql(sql: str, env: str = "qas") -> str:
    """Esegue UNA query SQL in sola lettura via Statement Execution API.
    Il chiamante e' responsabile di decidere se 'env' puo' essere 'prd' —
    questa funzione non ha una propria whitelist di ambienti, e' la sola
    run_sql_qas() (usata dal blocco automatico) a impedire 'prd'
    strutturalmente. Il controllo sola-lettura invece vale SEMPRE, qui,
    anche per PRD: non e' un limite del canale automatico, e' un limite
    della funzione stessa."""
    if not _is_read_only_sql(sql):
        raise SqlError("Rifiutata: solo query di sola lettura (SELECT/SHOW/DESCRIBE/EXPLAIN), una alla volta.")

    cfg = _env_config(env)
    warehouse_id = cfg["warehouse_id"]
    if not warehouse_id:
        raise SqlError(
            f'Nessun SQL warehouse configurato per l\'ambiente "{env}" '
            f"(DATABRICKS_{env.upper()}_WAREHOUSE_ID in .env)."
        )
    host = cfg["host"]
    headers = {"Authorization": f"Bearer {_get_token(env)}"}

    resp = requests.post(
        f"{host}/api/2.0/sql/statements",
        headers=headers,
        json={
            "statement": sql,
            "warehouse_id": warehouse_id,
            "wait_timeout": _SQL_WAIT_TIMEOUT,
            "row_limit": _SQL_ROW_LIMIT,
        },
        timeout=_TIMEOUT + 30,  # oltre il wait_timeout lato Databricks, margine per il round-trip HTTP
    )
    resp.raise_for_status()
    data = _poll_statement(host, headers, resp.json()["statement_id"], resp.json())
    return _format_sql_result(data)


def run_sql_qas(sql: str) -> str:
    """Unico entry point raggiungibile dal blocco ```dbsql``` automatico —
    'env' e' fisso a qas, non e' un parametro che il testo estratto da
    Claude puo' influenzare in alcun modo."""
    return run_sql(sql, env="qas")


async def extract_and_execute(text: str) -> str:
    """Estrae ed esegue ogni blocco ```genie```/```dbsql``` (solo QAS per
    entrambi), ritorna il testo ripulito con gli esiti in fondo — stesso
    pattern di core/browser.py::extract_and_execute()."""
    import asyncio

    outcomes: list[str] = []

    for m in GENIE_BLOCK_RE.finditer(text):
        try:
            action = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        question = action.get("question")
        if not question:
            continue
        try:
            answer = await asyncio.to_thread(ask_genie_qas, question)
            outcomes.append(f"Genie (QAS): {answer}")
        except GenieError as e:
            outcomes.append(f"Genie: {e}")
        except requests.RequestException as e:
            outcomes.append(f"Genie: errore di rete ({e}).")

    for m in SQL_BLOCK_RE.finditer(text):
        try:
            action = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        sql = action.get("sql")
        if not sql:
            continue
        try:
            result = await asyncio.to_thread(run_sql_qas, sql)
            outcomes.append(f"SQL (QAS):\n{result}")
        except SqlError as e:
            outcomes.append(f"SQL: {e}")
        except requests.RequestException as e:
            outcomes.append(f"SQL: errore di rete ({e}).")

    if not outcomes:
        return text

    cleaned = SQL_BLOCK_RE.sub("", GENIE_BLOCK_RE.sub("", text)).strip()
    return f"{cleaned}\n\n{chr(10).join(outcomes)}".strip()
