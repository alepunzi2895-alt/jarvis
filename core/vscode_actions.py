"""
JARVIS — apre un progetto in VS Code e delega una modifica vera a Claude
Code (il CLI, non il motore API di JARVIS) — richiesta esplicita di
Alessandro (2026-09-16): "rendere Jarvis in grado di usare VS Code, aprire
progetti, scrivere prompt al Claude Code per modifiche". Stesso pattern di
core/browser.py/core/mail_actions.py: Claude (nella chat normale) emette
un blocco ```vscode``` in fondo alla risposta, extract_and_execute() lo
estrae ed esegue.

Ambito volutamente ristretto ai workspace gia' noti/autorizzati
(core/claude_bridge.py::WORKSPACES, gia' dentro la whitelist di
SystemExecutor) — scelta esplicita sua (2026-09-16), niente path
arbitrari. Le modifiche sono autonome (stesso livello di fiducia gia' in
uso per read_file/write_file sugli altri workspace, sua scelta esplicita):
"git push" resta comunque SEMPRE dietro conferma esplicita — e' la
whitelist di SystemExecutor a deciderlo, invariata da questo modulo.

Esecuzione in un THREAD dedicato, mai un asyncio.create_task: sia bot.py
sia core/voice/daemon.py possono chiamare extract_and_execute da un loop
che si chiude a fine chiamata (asyncio.run() per singola interazione lato
voce) — un task asyncio non atteso verrebbe cancellato prima del termine,
un thread no (stesso principio gia' documentato in
core/brain.py::log_interaction). Un vero task di coding puo' richiedere
piu' turni/minuti, molto piu' di un blocco browser/mail_draft — bloccare
la risposta principale fino al termine sarebbe una latenza inaccettabile,
quindi il risultato arriva su Telegram quando e' pronto, non nella
risposta immediata.
"""

from __future__ import annotations

import json
import re

from core.executor_singleton import executor

VSCODE_BLOCK_RE = re.compile(r"```vscode\s*\n(.*?)\n```", re.DOTALL)

# Duplicati apposta invece di importarli da core/claude_bridge.py: quel
# modulo importa questo per il blocco ```vscode``` (vedi
# _run_post_processing) — importare da li' creerebbe un ciclo. Stessi
# valori/default, nessun accoppiamento reale (due letture di env var).
def resolve_project_path(name: str) -> str | None:
    """Pubblica: usata sia dal blocco ```vscode``` sia da bot.py::/code."""
    from core.claude_bridge import WORKSPACES  # import qui: evita il ciclo (claude_bridge importa questo modulo)

    path = WORKSPACES.get((name or "").strip().lower())
    if not path or not executor._in_whitelist(path):
        return None
    return path


def _open_in_vscode(path: str) -> str:
    result = executor.open_vscode(path)
    if not result.ok:
        return f"Non sono riuscito ad aprire VS Code: {result.stderr}"
    return "VS Code aperto."


def start_claude_code_task(project: str, path: str, prompt: str, mode: str = "edit", channel: str = "telegram") -> str:
    """Prompt a Claude Code tramite core/coding_tasks.py: lavoro tracciato, con
    resoconto su Telegram, dashboard e voce (channel) quando finisce."""
    from core import coding_tasks  # import qui: coding_tasks importa feed/memoria, qui non serve a freddo

    try:
        job = coding_tasks.start_task("claude", project, prompt, mode=mode, explicit=True, channel=channel)
    except ValueError as error:
        return str(error)
    return f'Claude Code al lavoro su "{project}" (lavoro {job["job_id"]}). Ti leggo il resoconto quando finisce.'


async def extract_and_execute(text: str, channel: str = "web") -> str:
    matches = list(VSCODE_BLOCK_RE.finditer(text))
    if not matches:
        return text

    outcomes: list[str] = []
    for m in matches:
        try:
            action = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue

        project = (action.get("project") or "").strip()
        prompt = (action.get("prompt") or "").strip()
        if not project:
            continue

        path = resolve_project_path(project)
        if not path:
            outcomes.append(f'Progetto "{project}" non riconosciuto o non autorizzato.')
            continue

        outcomes.append(_open_in_vscode(path))
        if prompt:
            mode = action.get("mode") if action.get("mode") in {"read", "edit"} else "edit"
            outcomes.append(start_claude_code_task(project, path, prompt, mode=mode, channel=channel))

    cleaned = VSCODE_BLOCK_RE.sub("", text).strip()
    if outcomes:
        cleaned = f"{cleaned}\n\n{' '.join(outcomes)}".strip()
    return cleaned
