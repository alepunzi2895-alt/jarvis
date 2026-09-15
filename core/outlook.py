"""
JARVIS — Outlook desktop via COM (pywin32), non Graph API ne' browser.
Riusa la sessione GIA' autenticata del client Outlook classico installato
su questa macchina — zero credenziali/OAuth da gestire, ma richiede
Outlook desktop installato (e piu' affidabile se e' anche aperto).

Sola lettura, sempre: nessuna funzione qui chiama .Send()/.Delete()/.Move()
su un oggetto Outlook — solo proprieta' lette da MAPIFolder.Items. Stessa
filosofia di core/browser.py per Teams: leggere si', agire mai da soli.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

# Le varianti reali con cui Alessandro chiede la posta a voce sono molte piu' di
# quelle che coprivamo all'inizio: "mi leggi l'ultima mail", "puoi leggermi la
# mail", "mi controlli la posta?" cadevano tutte fuori (verbo coniugato +
# pronome/articolo in mezzo) e finivano a Claude come chiacchiera. Ora: radice
# del verbo + fino a ~20 caratteri di riempimento + il sostantivo.
OUTLOOK_INTENT_RE = re.compile(
    r"\b(?:controll|guard|verific|legg|apr)\w*\b[^.?!]{0,20}?"
    r"\b(?:posta|mail|email|e-mail|inbox)\b"
    r"|\bposta\s+in\s+arrivo\b"
    r"|\b(?:ho|ci\s+sono)\s+(?:nuove\s+|delle\s+)?(?:mail|email)\b"
    r"|\bnuove\s+(?:mail|email)\b"
    # "quante mail (ho)?", "mail non lette" — nessuno dei pattern sopra li
    # copriva (nessuna radice verbale, "quante"/aggettivo invece di verbo).
    r"|\bquant[eo]\s+(?:mail|email)\b"
    r"|\b(?:mail|email)\w*[^.?!]{0,15}?\bnon\s+lett[ei]\b",
    re.IGNORECASE,
)

# Sottoinsieme di OUTLOOK_INTENT_RE che chiede specificamente il CONTEGGIO
# delle non lette (non la lista/il contenuto) — risposta diversa e piu'
# efficiente (core/outlook.py::count_unread_emails*, mai un limite di 8
# come list_recent_emails che tronca la lista).
UNREAD_COUNT_RE = re.compile(r"\bquant[eo]\b|\bnon\s+lett[ei]\b", re.IGNORECASE)

_SNIPPET_CHARS = 200
# olFolderInbox = 6 (costante Outlook, non serve importare win32com.client.constants
# per un solo valore — evita un giro COM in piu' solo per risolvere il nome).
_OL_FOLDER_INBOX = 6


class OutlookError(Exception):
    pass


@dataclass
class EmailSummary:
    sender: str
    subject: str
    received: str
    unread: bool
    snippet: str


# "Server execution failed" (HRESULT 0x80080005) e simili sono errori COM
# transitori ben noti con Outlook desktop — capitano quando Outlook e'
# momentaneamente occupato (sync in corso, un dialogo in primo piano, ecc.)
# e quasi sempre spariscono da soli dopo una breve attesa. Verificato dal
# vivo il 2026-09-15: una chiamata falliva con questo identico errore,
# la successiva (pochi minuti dopo, nessuna modifica di configurazione)
# e' andata a buon fine — non un problema di configurazione, un blip.
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SEC = 1.5


def _run_in_fresh_thread(fn, *args):
    """Esegue fn(*args) in un thread OS nuovo di zecca, mai riusato — i
    chiamanti sincroni (core/intents.py) girano gia' su un thread preso dal
    pool CONDIVISO di asyncio.to_thread (bot.py/web_bridge.py), che ricicla
    gli stessi thread OS per chiamate diverse nel tempo. CoInitialize/
    CoUninitialize sono per-thread: un thread riciclato che ha gia' ospitato
    un'altra chiamata COM in passato puo' lasciare l'apartment STA in uno
    stato sporco — causa sospetta (non confermata, ma verosimile) di un
    fallimento 0x80080005 mai riprodotto isolando la stessa identica
    chiamata in un processo/thread tutto suo. Un thread dedicato per ogni
    chiamata elimina il sospetto alla radice, a costo trascurabile."""
    result: dict = {}

    def _target():
        try:
            result["value"] = fn(*args)
        except Exception as e:  # noqa: BLE001 — ripropagato tale e quale al chiamante
            result["error"] = e

    t = threading.Thread(target=_target)
    t.start()
    t.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


def _fetch_recent_sync(count: int, unread_only: bool) -> list[EmailSummary]:
    """Gira SEMPRE su un thread separato (CoInitialize e' per-thread) — mai
    chiamata direttamente dal thread principale di bot.py/daemon.py."""
    try:
        import time
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise OutlookError(f"pywin32 non installato: {e}") from e

    pythoncom.CoInitialize()
    try:
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                outlook = win32com.client.Dispatch("Outlook.Application")
                namespace = outlook.GetNamespace("MAPI")
                inbox = namespace.GetDefaultFolder(_OL_FOLDER_INBOX)
                items = inbox.Items
                items.Sort("[ReceivedTime]", True)  # True = decrescente, le piu' recenti prima

                results: list[EmailSummary] = []
                for item in items:
                    try:
                        is_unread = bool(getattr(item, "UnRead", False))
                        if unread_only and not is_unread:
                            continue
                        body = (getattr(item, "Body", "") or "").strip().replace("\r\n", " ")
                        results.append(
                            EmailSummary(
                                sender=getattr(item, "SenderName", "sconosciuto") or "sconosciuto",
                                subject=getattr(item, "Subject", "") or "(nessun oggetto)",
                                received=str(getattr(item, "ReceivedTime", "")),
                                unread=is_unread,
                                snippet=body[:_SNIPPET_CHARS] + ("…" if len(body) > _SNIPPET_CHARS else ""),
                            )
                        )
                    except Exception:
                        continue  # una singola mail malformata non deve far fallire tutto l'elenco
                    if len(results) >= count:
                        break
                return results
            except Exception as e:  # noqa: BLE001 — COM puo' fallire in tanti modi diversi, molti transitori
                last_error = e
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY_SEC)

        raise OutlookError(
            "Non riesco a leggere Outlook — verifica che sia installato e configurato "
            f"su questa macchina (dettaglio: {last_error})."
        ) from last_error
    finally:
        pythoncom.CoUninitialize()


def _count_unread_sync() -> int:
    """Come _fetch_recent_sync ma per il solo conteggio — usa
    MAPIFolder.UnReadItemCount (un attributo gia' calcolato da Outlook, non
    un giro su tutti gli item) invece di list_recent_emails_sync(unread_only=
    True), che tronca a `count` risultati e darebbe un numero SBAGLIATO (per
    difetto) se le non lette fossero piu' del limite."""
    try:
        import time
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise OutlookError(f"pywin32 non installato: {e}") from e

    pythoncom.CoInitialize()
    try:
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                outlook = win32com.client.Dispatch("Outlook.Application")
                namespace = outlook.GetNamespace("MAPI")
                inbox = namespace.GetDefaultFolder(_OL_FOLDER_INBOX)
                return int(inbox.UnReadItemCount)
            except Exception as e:  # noqa: BLE001 — stesso pattern di _fetch_recent_sync
                last_error = e
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY_SEC)

        raise OutlookError(
            "Non riesco a leggere Outlook — verifica che sia installato e configurato "
            f"su questa macchina (dettaglio: {last_error})."
        ) from last_error
    finally:
        pythoncom.CoUninitialize()


async def count_unread_emails() -> int:
    import asyncio

    return await asyncio.to_thread(_run_in_fresh_thread, _count_unread_sync)


def count_unread_emails_sync() -> int:
    return _run_in_fresh_thread(_count_unread_sync)


async def list_recent_emails(count: int = 8, unread_only: bool = False) -> list[EmailSummary]:
    import asyncio

    return await asyncio.to_thread(_run_in_fresh_thread, _fetch_recent_sync, count, unread_only)


def list_recent_emails_sync(count: int = 8, unread_only: bool = False) -> list[EmailSummary]:
    """Per chiamanti gia' sincroni (es. core/intents.py) che gestiscono loro
    stessi il threading (asyncio.to_thread lato bot.py/web_bridge.py) — vedi
    _run_in_fresh_thread per il perche' non basta gia' essere su UN thread
    qualunque, deve essere uno dedicato e mai riusato."""
    return _run_in_fresh_thread(_fetch_recent_sync, count, unread_only)


def format_unread_count(n: int, voice: bool) -> str:
    if n == 0:
        return "Nessuna mail non letta, Signore." if voice else "Nessuna mail non letta."
    if n == 1:
        return "Hai una mail non letta, Signore." if voice else "1 mail non letta."
    return f"Hai {n} mail non lette, Signore." if voice else f"{n} mail non lette."


def format_summary(emails: list[EmailSummary], voice: bool) -> str:
    if not emails:
        return "Nessuna mail in arrivo, Signore." if voice else "Nessuna mail trovata."

    if voice:
        n_unread = sum(1 for e in emails if e.unread)
        parts = [f"{e.sender}: {e.subject}" for e in emails[:3]]
        prefix = f"{n_unread} non lette. " if n_unread else ""
        return f"{prefix}Ultime mail — {'; '.join(parts)}, Signore."

    lines = ["Posta in arrivo:", ""]
    for e in emails:
        flag = "🔵 " if e.unread else ""
        lines.append(f"{flag}**{e.sender}** — {e.subject} ({e.received})")
        if e.snippet:
            lines.append(f"  {e.snippet}")
        lines.append("")
    return "\n".join(lines).strip()
