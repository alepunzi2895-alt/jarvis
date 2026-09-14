"""
JARVIS — Databricks (Iveco): OAuth M2M (service principal) + Genie
Conversation API (docs.databricks.com/aws/en/genie/conversation-api).

QAS e' l'unico ambiente che Claude puo' raggiungere da solo (blocco
```genie``` in fondo alla risposta, stesso pattern di core/browser.py).
PRD (produzione) NON e' mai raggiungibile da quel percorso automatico per
scelta esplicita di sicurezza: richiede il comando dedicato /genie_prd su
Telegram, che passa comunque dalla stessa conferma /confirm-/deny gia'
usata da SystemExecutor per le azioni rischiose — credenziali di
produzione, non ci si va per tentativi ne' per decisione autonoma di
Claude.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid

import requests

GENIE_BLOCK_RE = re.compile(r"```genie\s*\n(.*?)\n```", re.DOTALL)

_TIMEOUT = 30
_POLL_INTERVAL = 2.0
_POLL_MAX_SECONDS = 300  # Genie puo' impiegare qualche minuto su query pesanti (linea guida Databricks)

_TERMINAL_OK = {"COMPLETED"}
_TERMINAL_FAIL = {"FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}

_ENVIRONMENTS = {
    "qas": {
        "host": os.getenv("DATABRICKS_QAS_HOST", "").rstrip("/"),
        "client_id": os.getenv("DATABRICKS_QAS_CLIENT_ID", ""),
        "client_secret": os.getenv("DATABRICKS_QAS_CLIENT_SECRET", ""),
        "space_id": os.getenv("DATABRICKS_QAS_GENIE_SPACE_ID", ""),
    },
    "prd": {
        "host": os.getenv("DATABRICKS_PRD_HOST", "").rstrip("/"),
        "client_id": os.getenv("DATABRICKS_PRD_CLIENT_ID", ""),
        "client_secret": os.getenv("DATABRICKS_PRD_CLIENT_SECRET", ""),
        "space_id": os.getenv("DATABRICKS_PRD_GENIE_SPACE_ID", ""),
    },
}

_token_cache: dict[str, tuple[str, float]] = {}  # env -> (token, scadenza_epoch)
_pending: dict[str, str] = {}  # token /confirm -> domanda in sospeso per PRD


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


def stage_prd_confirmation(question: str) -> str:
    """Mette in sospeso una domanda per l'ambiente PRD, ritorna il token da
    confermare — stesso pattern (token corto, dizionario in memoria) di
    SystemExecutor._stage_confirmation(), volutamente separato invece di
    condiviso: PRD Databricks non ha nulla a che fare con le azioni di
    sistema che SystemExecutor gestisce."""
    token = uuid.uuid4().hex[:8]
    _pending[token] = question
    return token


def confirm_prd(token: str) -> str:
    question = _pending.pop(token, None)
    if question is None:
        raise GenieError("Token non valido o scaduto.")
    return ask_genie(question, env="prd")


def deny_prd(token: str) -> bool:
    return _pending.pop(token, None) is not None


async def extract_and_execute(text: str) -> str:
    """Estrae ed esegue ogni blocco ```genie``` (solo QAS), ritorna il testo
    ripulito con la risposta di Genie in fondo — stesso pattern di
    core/browser.py::extract_and_execute()."""
    import asyncio

    matches = list(GENIE_BLOCK_RE.finditer(text))
    if not matches:
        return text

    outcomes: list[str] = []
    for m in matches:
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

    cleaned = GENIE_BLOCK_RE.sub("", text).strip()
    if outcomes:
        cleaned = f"{cleaned}\n\n{chr(10).join(outcomes)}".strip()
    return cleaned
