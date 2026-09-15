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
    r"|\bnuove\s+(?:mail|email)\b",
    re.IGNORECASE,
)

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


def _fetch_recent_sync(count: int, unread_only: bool) -> list[EmailSummary]:
    """Gira SEMPRE su un thread separato (CoInitialize e' per-thread) — mai
    chiamata direttamente dal thread principale di bot.py/daemon.py."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise OutlookError(f"pywin32 non installato: {e}") from e

    pythoncom.CoInitialize()
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
    except Exception as e:  # noqa: BLE001 — COM puo' fallire in tanti modi diversi (Outlook chiuso, profilo assente, ecc.)
        raise OutlookError(
            "Non riesco a leggere Outlook — verifica che sia installato e configurato "
            f"su questa macchina (dettaglio: {e})."
        ) from e
    finally:
        pythoncom.CoUninitialize()


async def list_recent_emails(count: int = 8, unread_only: bool = False) -> list[EmailSummary]:
    import asyncio

    return await asyncio.to_thread(_fetch_recent_sync, count, unread_only)


def list_recent_emails_sync(count: int = 8, unread_only: bool = False) -> list[EmailSummary]:
    """Per chiamanti gia' sincroni (es. core/intents.py) che gestiscono loro
    stessi il threading (asyncio.to_thread lato bot.py/web_bridge.py)."""
    return _fetch_recent_sync(count, unread_only)


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
