"""
JARVIS — portare in primo piano una finestra lanciata da un processo che
gira in background (bot.py e' un task pianificato Windows, senza focus
proprio). Windows nega di default SetForegroundWindow a un processo che non
e' gia' lui stesso in primo piano; AttachThreadInput e' il trick standard
per aggirarlo — verificato dal vivo (2026-09-15) contro un'app reale
(mspaint.exe) prima di usarlo qui.

Due usi reali:
- core/system_executor.py::open_app — il PID e' noto (viene da
  subprocess.Popen direttamente).
- core/browser.py::BrowserAgent.open()/search() — il PID NON e' noto (
  Playwright non lo espone per un contesto persistente), trovato invece per
  sottostringa nella cmdline (la cartella del profilo, unica per il nostro
  processo anche con altre finestre Chrome gia' aperte).
"""

from __future__ import annotations

import threading
import time

import psutil


def find_window_for_pids(pids: set[int], timeout: float = 4.0) -> int | None:
    import win32gui
    import win32process

    deadline = time.time() + timeout
    while time.time() < deadline:
        found: list[int] = []

        def _cb(hwnd: int, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, wpid = win32process.GetWindowThreadProcessId(hwnd)
            if wpid in pids and win32gui.GetWindowText(hwnd):
                found.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        if found:
            return found[0]
        time.sleep(0.2)
    return None


def find_window_for_pid(pid: int, timeout: float = 4.0) -> int | None:
    """Come find_window_for_pids, ma include anche i figli del processo dato
    — alcuni launcher (es. Notepad su Windows 11) spawnano un child e
    escono subito, il PID originale non possiede piu' nessuna finestra."""
    try:
        proc = psutil.Process(pid)
        pids = {pid} | {c.pid for c in proc.children(recursive=True)}
    except psutil.NoSuchProcess:
        pids = {pid}
    return find_window_for_pids(pids, timeout)


def force_foreground(hwnd: int) -> None:
    import win32api
    import win32con
    import win32gui
    import win32process

    fg_hwnd = win32gui.GetForegroundWindow()
    fg_thread, _ = win32process.GetWindowThreadProcessId(fg_hwnd)
    target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
    cur_thread = win32api.GetCurrentThreadId()
    attached = bool(fg_thread) and bool(target_thread) and fg_thread != target_thread
    if attached:
        win32process.AttachThreadInput(cur_thread, fg_thread, True)
        win32process.AttachThreadInput(target_thread, fg_thread, True)
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if attached:
            win32process.AttachThreadInput(cur_thread, fg_thread, False)
            win32process.AttachThreadInput(target_thread, fg_thread, False)


def bring_pid_to_foreground_bg(pid: int) -> None:
    """Fire-and-forget: non deve mai ritardare la risposta di chi chiama
    (fino a 4s di polling per trovare la finestra)."""

    def work() -> None:
        try:
            hwnd = find_window_for_pid(pid)
            if hwnd:
                force_foreground(hwnd)
        except Exception:  # noqa: BLE001 — mai far fallire l'apertura per questo
            pass

    threading.Thread(target=work, daemon=True).start()


def bring_matching_to_foreground_bg(cmdline_marker: str, process_name_contains: str = "chrome", timeout: float = 4.0) -> None:
    """Come bring_pid_to_foreground_bg, ma per processi il cui PID non e'
    direttamente disponibile — trovati per sottostringa nella riga di
    comando (es. la cartella del profilo Playwright, che non collide con
    altre finestre Chrome gia' aperte dall'utente)."""

    def work() -> None:
        try:
            deadline = time.time() + timeout
            pids: set[int] = set()
            while time.time() < deadline and not pids:
                for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                    try:
                        name = (proc.info["name"] or "").lower()
                        if process_name_contains not in name:
                            continue
                        cmdline = " ".join(proc.info["cmdline"] or [])
                        if cmdline_marker in cmdline:
                            pids.add(proc.info["pid"])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if not pids:
                    time.sleep(0.2)
            if not pids:
                return
            hwnd = find_window_for_pids(pids, timeout=max(0.5, deadline - time.time()))
            if hwnd:
                force_foreground(hwnd)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=work, daemon=True).start()
