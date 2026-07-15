"""
JARVIS — esecuzione di azioni di sistema decise da Claude.

Stesso pattern di core/browser.py: per i comandi semplici e brevi ci pensa
core/intents.py PRIMA di interpellare Claude (zero costo/latenza). Per
richieste composte o sfumate che core/intents.py lascia passare (es. "apri
VS code e poi dimmi che ore sono", oppure una richiesta dedotta da
ragionamento, non da un comando diretto), Claude puo' comunque emettere IN
FONDO alla risposta un blocco:

```system
{"action":"open_app","name":"..."}
```

extract_and_execute() lo estrae, esegue tramite SystemExecutor, ripulisce il
testo — stessa identica meccanica di core/browser.py.
"""

import json
import re

from core.system_executor import SystemExecutor

SYSTEM_BLOCK_RE = re.compile(r"```system\s*\n(.*?)\n```", re.DOTALL)

_POWER_LABELS = {"shutdown": "spegnere il PC", "restart": "riavviare il PC", "logoff": "disconnettere l'utente"}


def _run_action(action: dict, executor: SystemExecutor) -> str | None:
    kind = action.get("action")

    if kind == "open_app" and action.get("name"):
        r = executor.open_app(action["name"])
        return f"Aperto {action['name']}." if r.ok else f"Errore apertura {action['name']}: {r.stderr}"

    if kind == "close_app" and action.get("name"):
        r = executor.close_app(action["name"])
        return f"Chiuso {action['name']}." if r.ok else f"Errore chiusura {action['name']}: {r.stderr}"

    if kind == "volume" and action.get("direction"):
        r = executor.volume(action["direction"])
        return "Volume regolato." if r.ok else f"Errore volume: {r.stderr}"

    if kind == "lock":
        r = executor.lock_workstation()
        return "Schermo bloccato." if r.ok else f"Errore: {r.stderr}"

    if kind == "show_desktop":
        r = executor.show_desktop()
        return "Desktop mostrato." if r.ok else f"Errore: {r.stderr}"

    if kind == "screenshot":
        r = executor.screenshot()
        return f"Screenshot salvato in {r.stdout}." if r.ok else f"Errore screenshot: {r.stderr}"

    if kind == "power" and action.get("mode") in _POWER_LABELS:
        r = executor.power_action(action["mode"])
        if r.needs_confirmation:
            label = _POWER_LABELS[action["mode"]]
            return f"Per {label} serve conferma: /confirm {r.token} oppure /deny {r.token}."
        return "Fatto." if r.ok else f"Errore: {r.stderr}"

    return None


async def extract_and_execute(text: str, executor: SystemExecutor) -> str:
    """Estrae ed esegue ogni blocco ```system```, ritorna il testo ripulito
    con l'esito dell'azione in fondo."""
    matches = list(SYSTEM_BLOCK_RE.finditer(text))
    if not matches:
        return text

    outcomes: list[str] = []
    for m in matches:
        try:
            action = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        try:
            outcome = _run_action(action, executor)
        except Exception as e:  # noqa: BLE001
            outcome = f"Errore azione di sistema: {e}"
        if outcome:
            outcomes.append(outcome)

    cleaned = SYSTEM_BLOCK_RE.sub("", text).strip()
    if outcomes:
        cleaned = f"{cleaned}\n\n{' '.join(outcomes)}".strip()
    return cleaned
