"""
JARVIS — chat per progetto con una sessione Claude Code viva.

Un processo `claude -p --input-format stream-json` per progetto: ogni prompt
e' una riga JSON su stdin, gli eventi (testo, strumenti, risultato) arrivano
su stdout e finiscono in un file JSONL per progetto. La chat e' leggibile
dalla dashboard (/progetti) e il risultato di ogni turno viene registrato in
coding_tasks, cosi' la voce lo legge a fine lavoro come gli altri lavori.

Permessi: allowlist concordata con Alessandro (letture, modifiche, git in
lettura e commit su branch, npm/pytest). Nessun push, nessun rm, nessun
deploy: cio' che non e' in allowlist viene negato in headless.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import threading

from core import projects
from core.executor_singleton import executor

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / ".project-chats"

ALLOWED_TOOLS = [
    "Read", "Glob", "Grep", "Edit", "Write",
    "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git show*)", "Bash(git branch*)",
    "Bash(git switch -c*)", "Bash(git checkout -b*)", "Bash(git add*)", "Bash(git commit*)",
    "Bash(npm install*)", "Bash(npm ci*)", "Bash(npm run *)", "Bash(npm test*)", "Bash(npx tsc*)",
    "Bash(python -m pytest*)", "Bash(pytest*)", "Bash(ls*)", "Bash(cat *)",
]
GUIDANCE = ("Sei Claude Code in una chat di progetto aperta da JARVIS per Alessandro. Rispondi in italiano, "
            "in modo breve: cosa hai fatto, file toccati, esito dei test. Non fare push, non lavorare su main, "
            "non eseguire deploy o cancellazioni. Se servono permessi non concessi, dillo e fermati.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectChat:
    def __init__(self, key: str, path: str):
        self.key, self.path = key, path
        self.file = STORE / f"{key}.jsonl"
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.session_id = ""
        self.busy = False
        self.last_prompt = ""
        self.events = self._load()

    # ── persistenza ────────────────────────────────────────────────
    def _load(self) -> list[dict]:
        try:
            lines = self.file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        items = []
        for line in lines[-500:]:
            try:
                items.append(json.loads(line))
            except ValueError:
                continue
        for item in reversed(items):
            if item.get("kind") == "session" and item.get("session_id"):
                self.session_id = item["session_id"]
                break
        return items

    def _add(self, kind: str, text: str = "", **extra) -> dict:
        item = dict(id=(self.events[-1]["id"] + 1) if self.events else 1, at=_now(), kind=kind,
                    text=text[:8000], **extra)
        self.events.append(item)
        STORE.mkdir(exist_ok=True)
        with self.file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    # ── processo ───────────────────────────────────────────────────
    def _command(self) -> list[str]:
        cmd = [os.getenv("CLAUDE_BIN", "claude"), "-p", "--input-format", "stream-json",
               "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
               "--permission-prompts", "none", "--strict-mcp-config", "--max-turns", "60",
               "--append-system-prompt", GUIDANCE, "--allowedTools", *ALLOWED_TOOLS]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        return cmd

    def _ensure_running(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)  # non ereditare la sessione del supervisore
        self.proc = subprocess.Popen(self._command(), cwd=self.path, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", errors="replace",
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._add("status", "Sessione ripresa." if self.session_id else "Sessione Claude Code avviata.")
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._drain_err, args=(self.proc,), daemon=True).start()

    def send(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            raise ValueError("Messaggio vuoto.")
        if not executor._in_whitelist(self.path):
            raise ValueError("Cartella in sola lettura: non autorizzata alle modifiche in JARVIS.")
        with self.lock:
            if self.busy:
                raise ValueError("Claude Code sta ancora lavorando: attendi il risultato del turno precedente.")
            self._ensure_running()
            self.busy = True
            self.last_prompt = text
            self._add("user", text)
            line = json.dumps({"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False)
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()

    def stop(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            self.busy = False
            self._add("status", "Sessione fermata.")

    def _drain_err(self, proc) -> None:
        for line in proc.stderr:
            line = line.strip()
            if line and "connectors are disabled" not in line:  # avviso innocuo del CLI
                with self.lock:
                    self._add("error", line[:500])

    def _read(self, proc) -> None:
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                self._handle(event)
        with self.lock:
            if self.busy:
                self.busy = False
                self._add("error", "Il processo si e' chiuso durante il turno. Il prossimo messaggio riprende la sessione.")
            else:
                self._add("status", "Processo chiuso.")

    def _handle(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            self.session_id = event.get("session_id", self.session_id)
            self._add("session", session_id=self.session_id)
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    self._add("text", block["text"])
                elif block.get("type") == "tool_use":
                    tool_input = block.get("input") or {}
                    target = tool_input.get("file_path") or tool_input.get("command") or tool_input.get("pattern") or ""
                    self._add("tool", f"{block.get('name', '')} {str(target)[:200]}".strip())
        elif kind == "result":
            self.busy = False
            self.session_id = event.get("session_id", self.session_id)
            failed = bool(event.get("is_error"))
            text = event.get("result") or ("Turno terminato con errore." if failed else "(nessun testo)")
            self._add("result", text, status="error" if failed else "done")
            self._record(text, "error" if failed else "done")

    def _record(self, text: str, status: str) -> None:
        from core import coding_tasks
        try:
            coding_tasks.record_finished("claude", self.key, self.last_prompt, status, text, self.path)
        except Exception:  # noqa: BLE001 — il registro non deve fermare la chat
            pass


_chats: dict[str, ProjectChat] = {}
_registry_lock = threading.Lock()


def _chat(project: str) -> ProjectChat:
    found = projects.find(project)
    if not found or not found.path or not Path(found.path).is_dir():
        raise ValueError("Progetto senza cartella locale.")
    with _registry_lock:
        if found.key not in _chats:
            _chats[found.key] = ProjectChat(found.key, str(Path(found.path).resolve()))
        return _chats[found.key]


def list_projects() -> list[dict]:
    rows = []
    for project in projects.catalog():
        if not project.path:
            continue
        chat = _chats.get(project.key)
        rows.append(dict(key=project.key, label=project.label, path=project.path,
                         editable=executor._in_whitelist(project.path), busy=bool(chat and chat.busy)))
    return rows


def history(project: str, after: int = 0) -> dict:
    chat = _chat(project)
    items = [item for item in chat.events if item["id"] > after]
    return {"events": items[-300:], "busy": chat.busy, "session_id": chat.session_id}


def send(project: str, text: str) -> dict:
    _chat(project).send(text)
    return {"ok": True}


def stop(project: str) -> dict:
    _chat(project).stop()
    return {"ok": True}
