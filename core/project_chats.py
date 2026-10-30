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
import re
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


CLAUDE_DIR = Path.home() / ".claude" / "projects"
RECENT_SEC = 120  # transcript modificato da meno di 2 minuti = sessione probabilmente in uso


def _transcript_dir(path) -> Path:
    """Claude Code salva le sessioni in ~/.claude/projects/<cwd con ogni carattere non alfanumerico -> ->."""
    return CLAUDE_DIR / re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _transcripts(path) -> list[Path]:
    folder = _transcript_dir(path)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


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

    # ── collegamento alla sessione (VS Code / terminale) ──────────
    def attach(self, session_id: str) -> None:
        """Riprende una sessione Claude Code esistente (--resume). Il prossimo messaggio continua da li'."""
        with self.lock:
            if self.busy:
                raise ValueError("Claude Code sta lavorando: attendi la fine del turno prima di cambiare sessione.")
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            self.proc = None
            self.session_id = session_id
            self._add("session", session_id=session_id)
            self._add("status", f"Collegata alla sessione {session_id[:8]}.")

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


def sessions(project: str) -> dict:
    chat = _chat(project)
    rows = []
    for file in _transcripts(chat.path)[:8]:
        age = datetime.now().timestamp() - file.stat().st_mtime
        rows.append(dict(session_id=file.stem, modified=datetime.fromtimestamp(file.stat().st_mtime).strftime("%H:%M"),
                         active=age < RECENT_SEC))
    return {"sessions": rows, "current": chat.session_id}


def attach(project: str, session_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f-]{20,}", session_id or ""):
        raise ValueError("Sessione non valida.")
    _chat(project).attach(session_id)
    return {"ok": True}


def prepare(project: str) -> str:
    """Chiamata all'apertura del progetto (anche a voce): se la chat non ha ancora una sessione,
    collega l'ultima sessione Claude Code del progetto (quella di VS Code o del terminale)."""
    chat = _chat(project)
    if chat.session_id:
        return chat.session_id
    files = _transcripts(chat.path)
    if not files:
        return ""
    chat.attach(files[0].stem)
    return files[0].stem


_chats: dict[str, ProjectChat] = {}
_registry_lock = threading.Lock()


def _chat(project: str) -> ProjectChat:
    found = projects.find(project)
    if not found or not found.path or not Path(found.path).is_dir():
        raise ValueError("Progetto senza cartella locale.")
    with _registry_lock:
        if found.key not in _chats:
            chat = ProjectChat(found.key, str(Path(found.path).resolve()))
            if not chat.session_id and _transcripts(chat.path):
                chat.attach(_transcripts(chat.path)[0].stem)  # prima apertura: ultima sessione del progetto
            _chats[found.key] = chat
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


_TRANSCRIPT_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _transcript_items(path: Path) -> list[dict]:
    """Messaggi di una sessione Claude Code letti dal transcript: stessa fonte per la chat JARVIS,
    per la sessione di VS Code e per il terminale (sono lo stesso file). Testo utente/assistente e strumenti."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    cached = _TRANSCRIPT_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    items = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") or {}
        content = message.get("content")
        stamp = str(record.get("timestamp", ""))[11:19]
        kind = record.get("type")
        if kind == "user":
            texts = [content] if isinstance(content, str) else [
                block.get("text", "") for block in content or [] if isinstance(block, dict) and block.get("type") == "text"]
            for text in texts:
                if text.strip() and not text.startswith("<"):
                    items.append(dict(kind="user", text=text[:8000], at=stamp))
        elif kind == "assistant":
            for block in content or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    items.append(dict(kind="text", text=block["text"][:8000], at=stamp))
                elif block.get("type") == "tool_use":
                    tool_input = block.get("input") or {}
                    target = tool_input.get("file_path") or tool_input.get("command") or tool_input.get("pattern") or ""
                    items.append(dict(kind="tool", text=f"{block.get('name', '')} {str(target)[:200]}".strip(), at=stamp))
    for index, item in enumerate(items, start=1):
        item["id"] = index
    _TRANSCRIPT_CACHE[str(path)] = (mtime, items)
    return items


def history(project: str, after: int = 0) -> dict:
    chat = _chat(project)
    transcript = _transcript_dir(chat.path) / f"{chat.session_id}.jsonl" if chat.session_id else None
    if transcript and transcript.is_file():
        # Sessione collegata: si vede cio' che sta scrivendo, anche se e' stata avviata da VS Code.
        items = [item for item in _transcript_items(transcript) if item["id"] > after]
        live = chat.busy or (datetime.now().timestamp() - transcript.stat().st_mtime) < RECENT_SEC
        return {"events": items[-300:], "busy": chat.busy, "live": live, "session_id": chat.session_id}
    items = [item for item in chat.events if item["id"] > after]
    return {"events": items[-300:], "busy": chat.busy, "live": chat.busy, "session_id": chat.session_id}


def send(project: str, text: str) -> dict:
    _chat(project).send(text)
    return {"ok": True}


def stop(project: str) -> dict:
    _chat(project).stop()
    return {"ok": True}
