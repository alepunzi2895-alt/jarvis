"""
JARVIS — SystemExecutor: azioni sul sistema operativo con whitelist esplicita.

Filosofia: whitelist, non blacklist. Un set esplicito di comandi/azioni
permessi esegue subito; tutto il resto (compreso ogni comando shell non
riconosciuto, o che tocca percorsi fuori dalle directory autorizzate) ritorna
`needs_confirmation` e non esegue nulla finche' non arriva una conferma
esplicita — stessa filosofia "conferma prima di ogni azione distruttiva o
irreversibile" gia' in uso nel resto di JARVIS.

Limite noto: il controllo sui percorsi toccati da un comando e' euristico
(cerca token che sembrano path assoluti o risalite `..`), non un parser
completo della sintassi PowerShell. Sufficiente per comandi generati in buona
fede da Claude/voce, non pensato come sandbox contro input avversariale.
"""

from __future__ import annotations

import re
import subprocess
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from core.obsidian import ObsidianVault

GIT_ALLOWED_SUBCOMMANDS = {"status", "log", "diff", "branch", "pull", "add", "commit"}
POWERSHELL_READONLY_CMDLETS = {
    "get-childitem", "get-content", "get-process", "get-command", "get-item",
    "dir", "type", "where",
}
PATH_TOKEN_RE = re.compile(r"([A-Za-z]:[\\/][^\s\"']+|\.\.[\\/][^\s\"']*)")

APP_REGISTRY: dict[str, str] = {
    "notepad": "notepad.exe",
    "blocco note": "notepad.exe",
    "esplora file": "explorer.exe",
    "explorer": "explorer.exe",
    "vs code": "code.exe",
    "visual studio code": "code.exe",
    "vscode": "code.exe",
}

# App Electron/portable che spesso non si registrano tra le "App Paths" di
# Windows — path relativi alla home utente, controllati solo se il file esiste.
KNOWN_USER_APPS: dict[str, str] = {
    "obsidian": r"AppData\Local\Programs\Obsidian\Obsidian.exe",
}


def _resolve_known_user_app(name: str) -> str | None:
    rel = KNOWN_USER_APPS.get(name)
    if not rel:
        return None
    candidate = Path.home() / rel
    return str(candidate) if candidate.is_file() else None


def _resolve_app_path(name: str) -> str | None:
    """Cerca il nome tra le 'App Paths' del registro di Windows — copre qualunque
    app installata che vi si registra (Chrome, VS Code, Obsidian, ecc.), senza
    dover elencare ogni eseguibile a mano in APP_REGISTRY."""
    try:
        import winreg
    except ImportError:
        return None

    exe_name = name if name.lower().endswith(".exe") else f"{name}.exe"
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    for hive, base in roots:
        try:
            with winreg.OpenKey(hive, f"{base}\\{exe_name}") as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value:
                    return value
        except OSError:
            continue
    return None


@dataclass
class ExecResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    needs_confirmation: bool = False
    token: str | None = None


class SystemExecutor:
    def __init__(self, allowed_dirs: list[str | Path], vault: ObsidianVault | None = None):
        self.allowed_dirs = [Path(d).resolve() for d in allowed_dirs]
        self.vault = vault
        self._pending: dict[str, dict] = {}

    # ── whitelist checks ──────────────────────────────────────────────

    def _in_whitelist(self, path: str | Path) -> bool:
        try:
            p_str = str(Path(path).resolve()).lower()
        except OSError:
            return False
        for d in self.allowed_dirs:
            d_str = str(d).lower()
            if p_str == d_str or p_str.startswith(d_str + "\\"):
                return True
        return False

    def _command_is_safe(self, cmd: str, cwd: str) -> bool:
        parts = cmd.strip().split()
        if not parts:
            return False
        head = parts[0].lower()
        if head == "git":
            if len(parts) < 2 or parts[1].lower() not in GIT_ALLOWED_SUBCOMMANDS:
                return False
        elif head not in POWERSHELL_READONLY_CMDLETS:
            return False

        for token in PATH_TOKEN_RE.findall(cmd):
            candidate = Path(token)
            if not candidate.is_absolute():
                candidate = Path(cwd) / candidate
            if not self._in_whitelist(candidate):
                return False
        return True

    # ── logging ────────────────────────────────────────────────────────

    def _log(self, action: str, detail: str) -> None:
        if not self.vault:
            return
        self.vault.write_note(
            f"Logs/system-{date.today().isoformat()}",
            f"- `{action}`: {detail}",
            mode="append",
        )

    # ── conferma azioni fuori whitelist ─────────────────────────────────

    def _stage_confirmation(self, kind: str, payload: dict) -> ExecResult:
        token = uuid.uuid4().hex[:8]
        self._pending[token] = {"kind": kind, **payload}
        return ExecResult(ok=False, needs_confirmation=True, token=token)

    def confirm(self, token: str) -> ExecResult:
        pending = self._pending.pop(token, None)
        if pending is None:
            return ExecResult(ok=False, stderr="Token non valido o scaduto.")
        kind = pending.pop("kind")
        if kind == "run":
            return self._run(force=True, **pending)
        if kind == "write_file":
            return self._write_file(force=True, **pending)
        if kind == "read_file":
            return self._read_file(force=True, **pending)
        if kind == "list_dir":
            return self._list_dir(force=True, **pending)
        return ExecResult(ok=False, stderr="Tipo di azione sconosciuto.")

    def deny(self, token: str) -> bool:
        return self._pending.pop(token, None) is not None

    # ── azioni ─────────────────────────────────────────────────────────

    def run(self, cmd: str, cwd: str | Path, timeout: int = 30) -> ExecResult:
        return self._run(cmd=cmd, cwd=str(cwd), timeout=timeout, force=False)

    def _run(self, cmd: str, cwd: str, timeout: int = 30, force: bool = False) -> ExecResult:
        if not force:
            if not self._in_whitelist(cwd):
                return self._stage_confirmation("run", {"cmd": cmd, "cwd": cwd, "timeout": timeout})
            if not self._command_is_safe(cmd, cwd):
                return self._stage_confirmation("run", {"cmd": cmd, "cwd": cwd, "timeout": timeout})

        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                cwd=cwd, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            self._log("run", f"TIMEOUT: `{cmd}` (cwd={cwd})")
            return ExecResult(ok=False, stderr="Timeout.")
        except OSError as e:
            return ExecResult(ok=False, stderr=str(e))

        self._log("run", f"`{cmd}` (cwd={cwd}) -> exit {proc.returncode}")
        return ExecResult(
            ok=proc.returncode == 0, stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode
        )

    def read_file(self, path: str | Path) -> ExecResult:
        return self._read_file(path=str(path), force=False)

    def _read_file(self, path: str, force: bool = False) -> ExecResult:
        if not force and not self._in_whitelist(path):
            return self._stage_confirmation("read_file", {"path": path})
        try:
            return ExecResult(ok=True, stdout=Path(path).read_text(encoding="utf-8"))
        except OSError as e:
            return ExecResult(ok=False, stderr=str(e))

    def write_file(self, path: str | Path, content: str) -> ExecResult:
        return self._write_file(path=str(path), content=content, force=False)

    def _write_file(self, path: str, content: str, force: bool = False) -> ExecResult:
        if not force and not self._in_whitelist(path):
            return self._stage_confirmation("write_file", {"path": path, "content": content})
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as e:
            return ExecResult(ok=False, stderr=str(e))
        self._log("write_file", path)
        return ExecResult(ok=True)

    def list_dir(self, path: str | Path) -> ExecResult:
        return self._list_dir(path=str(path), force=False)

    def _list_dir(self, path: str, force: bool = False) -> ExecResult:
        if not force and not self._in_whitelist(path):
            return self._stage_confirmation("list_dir", {"path": path})
        try:
            names = sorted(c.name for c in Path(path).iterdir())
            return ExecResult(ok=True, stdout="\n".join(names))
        except OSError as e:
            return ExecResult(ok=False, stderr=str(e))

    def open_app(self, name: str) -> ExecResult:
        clean = name.strip()
        exe = (
            APP_REGISTRY.get(clean.lower())
            or _resolve_app_path(clean)
            or _resolve_known_user_app(clean.lower())
        )
        if not exe:
            return ExecResult(ok=False, stderr=f'App "{name}" non trovata (ne\' nel registro ne\' tra le App Paths di Windows).')
        try:
            subprocess.Popen([exe])
        except OSError as e:
            return ExecResult(ok=False, stderr=str(e))
        self._log("open_app", name)
        return ExecResult(ok=True)

    def open_url(self, url: str) -> ExecResult:
        webbrowser.open(url)
        self._log("open_url", url)
        return ExecResult(ok=True)

    def git(self, action: str, repo: str | Path) -> ExecResult:
        return self.run(f"git {action}", cwd=repo)
