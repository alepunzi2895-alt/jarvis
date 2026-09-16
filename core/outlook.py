"""
JARVIS — Outlook desktop via COM (pywin32), non Graph API ne' browser.
Riusa la sessione GIA' autenticata del client Outlook classico installato
su questa macchina — zero credenziali/OAuth da gestire, ma richiede
Outlook desktop installato (e piu' affidabile se e' anche aperto).

Sola lettura per la posta esistente: nessuna funzione qui chiama .Send()/
.Delete()/.Move() su un oggetto Outlook gia' arrivato — solo proprieta'
lette da MAPIFolder.Items. Stessa filosofia di core/browser.py per Teams:
leggere si', agire mai da soli.

Unica eccezione, sicura per costruzione: create_draft_email() chiama SOLO
.Save() su un MailItem nuovo (mai .Send()) — il messaggio finisce nella
cartella Bozze di Outlook, mai spedito, resta sempre sotto il controllo di
Alessandro. Coerente con la regola "mai inviare messaggi senza conferma
esplicita" gia' in CLAUDE.md.
"""

from __future__ import annotations

import datetime as dt
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

# Query on-demand sul calendario (a differenza del promemoria automatico dei
# 15 minuti in bot.py::calendar_reminder_loop, che non passa da qui).
#
# 2026-09-16: "dimmi che riunioni ho in programma domani" trascritto dalla
# STT come "dici che riunioni un programma domani" (il "ho" garbled in
# "un") non incrociava NESSUna delle alternative sotto (tutte richiedevano
# "ho"/"ci sono" letterali subito dopo il sostantivo, o le parole esatte
# "agenda"/"cosa ho in calendario"/"calendario di") — la domanda cadeva
# intera su Claude (motore API diretto, senza alcun accesso al calendario)
# che rispondeva "non posso collegarmi al calendario". Aggiunta un'ultima
# alternativa piu' permissiva: sostantivo calendario + oggi/domani/
# programma/agenda entro una manciata di parole, in qualunque ordine, senza
# richiedere un verbo coniugato preciso — tollera meglio le trascrizioni
# imperfette senza intercettare frasi non pertinenti (il sostantivo
# meeting/riunione/appuntamento/impegno resta comunque obbligatorio).
CALENDAR_INTENT_RE = re.compile(
    r"\b(?:che|quali)\s+(?:meeting|riunion\w*|appuntament\w*|impegn\w*)\s+(?:ho|ci\s+sono)\b"
    r"|\bprossim\w+\s+(?:meeting|riunion\w*|appuntament\w*|impegn\w*)\b"
    r"|\bagenda\s+(?:di\s+oggi|del\s+giorno|di\s+domani)?\b"
    r"|\bcosa\s+ho\s+in\s+calendario\b"
    r"|\bcalendario\s+di\s+(?:oggi|domani)\b"
    r"|\b(?:meeting|riunion\w*|appuntament\w*|impegn\w*)\w*[^.?!]{0,25}?\b(?:oggi|domani|programma|agenda)\b"
    r"|\b(?:oggi|domani)\b[^.?!]{0,25}?\b(?:meeting|riunion\w*|appuntament\w*|impegn\w*)\b",
    re.IGNORECASE,
)

_TOMORROW_RE = re.compile(r"\bdomani\b", re.IGNORECASE)

_SNIPPET_CHARS = 200
# olFolderInbox = 6, olFolderCalendar = 9 (costanti Outlook, non serve
# importare win32com.client.constants per due soli valori — evita un giro
# COM in piu' solo per risolvere i nomi).
_OL_FOLDER_INBOX = 6
_OL_FOLDER_CALENDAR = 9


class OutlookError(Exception):
    pass


@dataclass
class EmailSummary:
    sender: str
    subject: str
    received: str
    unread: bool
    snippet: str


@dataclass
class CalendarEvent:
    subject: str
    start: dt.datetime
    end: dt.datetime
    location: str
    entry_id: str


# "Server execution failed" (HRESULT 0x80080005) e simili sono errori COM
# transitori ben noti con Outlook desktop — capitano quando Outlook e'
# momentaneamente occupato (sync in corso, un dialogo in primo piano, ecc.)
# e quasi sempre spariscono da soli dopo una breve attesa. Verificato dal
# vivo il 2026-09-15: una chiamata falliva con questo identico errore,
# la successiva (pochi minuti dopo, nessuna modifica di configurazione)
# e' andata a buon fine — non un problema di configurazione, un blip.
#
# 2026-09-16: causa reale trovata per le occorrenze RIPETUTE (non piu' un
# blip isolato) — bot.py::calendar_reminder_loop interroga il calendario
# ogni 60s in background, e una richiesta vocale/testuale sulla posta puo'
# capitare nello stesso istante. Outlook.exe processa le chiamate COM in
# arrivo in sostanza una alla volta: due thread Python diversi che aprono
# CIASCUNO un proprio Dispatch("Outlook.Application") in parallelo si
# scontrano lato server, non lato client — i retry da soli non bastavano
# perche' il conflitto si ripresentava identico ad ogni nuovo tentativo se
# l'altra chiamata era ancora in corso. _COM_LOCK serializza ogni accesso a
# Outlook DENTRO questo processo (mail, calendario, bozze) cosi' due
# chiamate non sono mai davvero concorrenti.
_COM_LOCK = threading.Lock()
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
    chiamata elimina il sospetto alla radice, a costo trascurabile.

    _COM_LOCK serializza il lavoro vero e proprio (dentro _target, non
    l'avvio del thread) — se due chiamate arrivano insieme, la seconda
    aspetta che la prima finisca invece di scontrarsi con lei dentro
    Outlook.exe."""
    result: dict = {}

    def _target():
        try:
            with _COM_LOCK:
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


def _com_time_to_datetime(t) -> dt.datetime:
    """pywintypes.datetime (tipo COM di Start/End) espone gia' year/month/...
    ma non e' un datetime nativo — le sottrazioni con dt.datetime.now() in
    bot.py::calendar_reminder_loop richiedono la conversione esplicita."""
    return dt.datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)


def _fetch_events_in_window_sync(start: dt.datetime, end: dt.datetime) -> list[CalendarEvent]:
    """Come _fetch_recent_sync ma sul calendario, su una finestra [start, end]
    esplicita. IncludeRecurrences=True prima di Restrict e' obbligatorio:
    senza, una riunione ricorrente settimanale sparirebbe dal filtro dopo la
    sua primissima occorrenza (Outlook la tratta come un singolo master item
    con la data originale, non una per occorrenza) — pattern standard per
    pywin32/Outlook COM."""
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
                calendar = namespace.GetDefaultFolder(_OL_FOLDER_CALENDAR)
                items = calendar.Items
                items.IncludeRecurrences = True
                items.Sort("[Start]")

                # Formato riconosciuto da Outlook.Restrict a prescindere dal
                # locale regionale di Windows — verificato dal vivo su
                # questa macchina (locale italiano) il 2026-09-16.
                fmt = "%m/%d/%Y %I:%M %p"
                restriction = f"[Start] >= '{start.strftime(fmt)}' AND [Start] <= '{end.strftime(fmt)}'"
                restricted = items.Restrict(restriction)

                results: list[CalendarEvent] = []
                for item in restricted:
                    try:
                        results.append(
                            CalendarEvent(
                                subject=getattr(item, "Subject", "") or "(senza titolo)",
                                start=_com_time_to_datetime(item.Start),
                                end=_com_time_to_datetime(item.End),
                                location=getattr(item, "Location", "") or "",
                                entry_id=getattr(item, "EntryID", "") or "",
                            )
                        )
                    except Exception:
                        continue  # un singolo evento malformato non deve far fallire tutto l'elenco
                results.sort(key=lambda e: e.start)
                return results
            except Exception as e:  # noqa: BLE001 — COM puo' fallire in tanti modi diversi, molti transitori
                last_error = e
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY_SEC)

        raise OutlookError(
            "Non riesco a leggere il calendario Outlook — verifica che sia installato e configurato "
            f"su questa macchina (dettaglio: {last_error})."
        ) from last_error
    finally:
        pythoncom.CoUninitialize()


def _fetch_upcoming_sync(minutes_ahead: int) -> list[CalendarEvent]:
    """Finestra relativa [ora, ora+minutes_ahead] — usata dal promemoria
    automatico (bot.py::calendar_reminder_loop), dove "quanto manca" conta
    piu' del giorno solare."""
    now = dt.datetime.now()
    return _fetch_events_in_window_sync(now, now + dt.timedelta(minutes=minutes_ahead))


async def get_upcoming_events(minutes_ahead: int = 20) -> list[CalendarEvent]:
    import asyncio

    return await asyncio.to_thread(_run_in_fresh_thread, _fetch_upcoming_sync, minutes_ahead)


def get_upcoming_events_sync(minutes_ahead: int = 20) -> list[CalendarEvent]:
    """Per chiamanti gia' sincroni (core/intents.py) — vedi list_recent_emails_sync."""
    return _run_in_fresh_thread(_fetch_upcoming_sync, minutes_ahead)


def get_events_for_day_sync(target: dt.date) -> list[CalendarEvent]:
    """Finestra sul giorno SOLARE (00:00–23:59) invece che relativa a ora —
    e' la finestra giusta per "che riunioni ho domani" (get_upcoming_events_sync
    con un minutes_ahead fisso non arriverebbe mai a coprire la giornata di
    domani per intero, e comunque avrebbe poco senso parlare di "minuti da
    ora" per un giorno diverso da oggi)."""
    start = dt.datetime.combine(target, dt.time.min)
    end = dt.datetime.combine(target, dt.time.max)
    return _run_in_fresh_thread(_fetch_events_in_window_sync, start, end)


def _create_draft_sync(to: str, subject: str, body: str) -> str:
    """CreateItem(0) = olMailItem. .Save() su un item MAI aperto con .Send()
    lo deposita nella cartella Bozze — comportamento COM standard, non serve
    specificare la cartella. Nessun .Send() esiste in questo modulo: e'
    strutturalmente impossibile che questa funzione spedisca qualcosa."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise OutlookError(f"pywin32 non installato: {e}") from e

    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        mail.Save()
        return f'Bozza creata in Outlook per "{to}" — controllala e invia tu, JARVIS non invia mai mail da solo.'
    except Exception as e:  # noqa: BLE001 — COM puo' fallire in tanti modi diversi
        raise OutlookError(f"Impossibile creare la bozza: {e}") from e
    finally:
        pythoncom.CoUninitialize()


async def create_draft_email(to: str, subject: str, body: str) -> str:
    import asyncio

    return await asyncio.to_thread(_run_in_fresh_thread, _create_draft_sync, to, subject, body)


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


def format_events(events: list[CalendarEvent], voice: bool, day: str = "oggi") -> str:
    """Per la query on-demand ("che meeting ho"), non per il promemoria
    automatico — vedi format_event_reminder. `day` e' solo per la frase
    ("oggi"/"domani"), la finestra vera e' gia' decisa da chi chiama
    get_upcoming_events_sync/get_events_for_day_sync."""
    label = "domani" if day == "domani" else "oggi"
    if not events:
        return f"Nessun impegno in calendario per {label}, Signore." if voice else f"Nessun impegno trovato per {label}."

    if voice:
        parts = [f"{e.subject} alle {e.start.strftime('%H:%M')}" for e in events[:3]]
        return f"Impegni di {label} — {'; '.join(parts)}, Signore."

    lines = [f"Impegni di {label}:", ""]
    for e in events:
        loc = f" @ {e.location}" if e.location else ""
        lines.append(f"**{e.start.strftime('%H:%M')}–{e.end.strftime('%H:%M')}** {e.subject}{loc}")
    return "\n".join(lines).strip()


def format_event_reminder(event: CalendarEvent, voice: bool) -> str:
    """Promemoria push (Telegram + voce) 15 minuti prima di un meeting —
    vedi bot.py::calendar_reminder_loop."""
    when = event.start.strftime("%H:%M")
    loc = f" ({event.location})" if event.location else ""
    if voice:
        return f"Tra 15 minuti ha inizio: {event.subject}{loc}, Signore."
    return f"📅 Tra 15 minuti: **{event.subject}** alle {when}{loc}."
