import datetime as dt
import threading

from core import outlook


def test_run_in_fresh_thread_returns_value():
    assert outlook._run_in_fresh_thread(lambda a, b: a + b, 2, 3) == 5


def test_run_in_fresh_thread_reraises_exceptions():
    def _boom():
        raise RuntimeError("kaboom")

    try:
        outlook._run_in_fresh_thread(_boom)
        assert False, "doveva sollevare"
    except RuntimeError as e:
        assert "kaboom" in str(e)


def test_run_in_fresh_thread_uses_a_different_thread():
    caller_thread = threading.get_ident()
    worker_thread = outlook._run_in_fresh_thread(threading.get_ident)
    assert worker_thread != caller_thread


def test_run_in_fresh_thread_serializes_concurrent_com_calls():
    """_COM_LOCK deve impedire a due chiamate di sovrapporsi davvero —
    causa reale scoperta il 2026-09-16: il loop dei promemoria calendario
    (ogni 60s) e una domanda vocale sulla posta potevano finire a parlare
    con Outlook.exe nello stesso istante, producendo "Server execution
    failed" (0x80080005) ripetuto invece di un blip isolato."""
    import time

    active = []
    overlapped = []

    def _slow_call(tag):
        active.append(tag)
        if len(active) > 1:
            overlapped.append(True)
        time.sleep(0.05)
        active.remove(tag)
        return tag

    results = []

    def _worker(tag):
        results.append(outlook._run_in_fresh_thread(_slow_call, tag))

    t1 = threading.Thread(target=_worker, args=("a",))
    t2 = threading.Thread(target=_worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not overlapped, "due chiamate Outlook COM sono girate in parallelo nonostante _COM_LOCK"
    assert sorted(results) == ["a", "b"]


def test_outlook_intent_regex_matches_common_phrases():
    assert outlook.OUTLOOK_INTENT_RE.search("controlla la posta")
    assert outlook.OUTLOOK_INTENT_RE.search("ho mail nuove?")
    assert outlook.OUTLOOK_INTENT_RE.search("ci sono nuove mail")
    assert outlook.OUTLOOK_INTENT_RE.search("leggi le mail")
    assert outlook.OUTLOOK_INTENT_RE.search("posta in arrivo")


def test_outlook_intent_regex_does_not_match_unrelated_text():
    assert not outlook.OUTLOOK_INTENT_RE.search("che tempo fa oggi")
    assert not outlook.OUTLOOK_INTENT_RE.search("apri chrome")


def test_outlook_intent_regex_matches_unread_count_phrasings():
    # "quante mail ho non lette" non aveva ne' una radice verbale ne' "nuove/
    # ho + mail" attaccati - nessuno dei pattern precedenti lo copriva.
    assert outlook.OUTLOOK_INTENT_RE.search("quante mail ho non lette?")
    assert outlook.OUTLOOK_INTENT_RE.search("quante email ho")
    assert outlook.OUTLOOK_INTENT_RE.search("ho mail non lette?")


def test_unread_count_re_matches_only_count_phrasings():
    assert outlook.UNREAD_COUNT_RE.search("quante mail ho non lette?")
    assert outlook.UNREAD_COUNT_RE.search("ho mail non lette?")
    assert not outlook.UNREAD_COUNT_RE.search("leggi l'ultima mail")


def test_format_unread_count_zero():
    assert outlook.format_unread_count(0, voice=False) == "Nessuna mail non letta."
    assert "Signore" in outlook.format_unread_count(0, voice=True)


def test_format_unread_count_singular():
    assert outlook.format_unread_count(1, voice=False) == "1 mail non letta."


def test_format_unread_count_plural():
    text = outlook.format_unread_count(5, voice=True)
    assert "5" in text and "Signore" in text


def test_format_summary_voice_mentions_sender_and_unread_count():
    emails = [
        outlook.EmailSummary(sender="Mario Rossi", subject="Riunione", received="2026-09-14 09:00", unread=True, snippet="ciao"),
        outlook.EmailSummary(sender="Newsletter", subject="Offerte", received="2026-09-14 08:00", unread=False, snippet=""),
    ]
    text = outlook.format_summary(emails, voice=True)
    assert "Mario Rossi" in text
    assert "Signore" in text
    assert "1 non lette" in text


def test_format_summary_text_flags_unread_and_includes_snippet():
    emails = [
        outlook.EmailSummary(sender="Mario Rossi", subject="Riunione", received="2026-09-14 09:00", unread=True, snippet="ciao, ci vediamo"),
        outlook.EmailSummary(sender="Newsletter", subject="Offerte", received="2026-09-14 08:00", unread=False, snippet=""),
    ]
    text = outlook.format_summary(emails, voice=False)
    assert "🔵" in text
    assert "Mario Rossi" in text and "Riunione" in text
    assert "ciao, ci vediamo" in text


def test_format_summary_empty_list():
    assert "Nessuna" in outlook.format_summary([], voice=False)
    assert "Signore" in outlook.format_summary([], voice=True)


# ── flusso interattivo "quale mail apro" (2026-09-16) — list_emails/read_email ──


def test_format_email_list_for_picking_numbers_subject_and_sender_no_badges():
    # 2026-09-16: "solo i titoli delle chat, no badge ecc" — niente flag
    # "(non letta)" per riga (il fatto "ci sono non lette" va detto una
    # volta sola, a parole, non ripetuto riga per riga nell'elenco).
    emails = [
        outlook.EmailSummary(sender="Mario Rossi", subject="Riunione", received="", unread=True, snippet="ciao"),
        outlook.EmailSummary(sender="Newsletter", subject="Offerte", received="", unread=False, snippet=""),
    ]
    text = outlook.format_email_list_for_picking(emails)
    assert "1. Riunione — Mario Rossi" in text
    assert "2. Offerte — Newsletter" in text
    assert "non letta" not in text.lower()


def test_format_email_list_for_picking_empty():
    assert "nessuna mail" in outlook.format_email_list_for_picking([]).lower()


def test_format_email_detail_includes_full_body():
    detail = outlook.EmailDetail(sender="Mario Rossi", subject="Riunione", received="2026-09-16 10:00", body="corpo completo della mail, non troncato")
    text = outlook.format_email_detail(detail)
    assert "Mario Rossi" in text
    assert "Riunione" in text
    assert "corpo completo della mail, non troncato" in text


# Nota: _fetch_recent_sync()/_fetch_upcoming_sync() non hanno un test a unit
# dedicato — tocca COM/Outlook desktop reale (hardware/software esterno),
# stesso stile gia' in uso nel repo per core/voice/camera.py (webcam):
# verificato dal vivo invece che con un mock fragile dell'import di
# win32com.client.


def test_calendar_intent_regex_matches_common_phrases():
    assert outlook.CALENDAR_INTENT_RE.search("che meeting ho oggi?")
    assert outlook.CALENDAR_INTENT_RE.search("quali riunioni ho")
    assert outlook.CALENDAR_INTENT_RE.search("prossimo appuntamento")
    assert outlook.CALENDAR_INTENT_RE.search("agenda di oggi")
    assert outlook.CALENDAR_INTENT_RE.search("cosa ho in calendario")
    assert outlook.CALENDAR_INTENT_RE.search("calendario di domani")


def test_calendar_intent_regex_does_not_match_unrelated_text():
    assert not outlook.CALENDAR_INTENT_RE.search("che tempo fa oggi")
    assert not outlook.CALENDAR_INTENT_RE.search("controlla la posta")


def test_calendar_intent_regex_matches_stt_garbled_phrasing():
    # 2026-09-16: "dimmi che riunioni ho in programma domani" trascritto
    # dalla STT come sotto (il verbo "ho" mangiato) non incrociava nessuna
    # delle alternative originali — la domanda cadeva su Claude, che non ha
    # nessun accesso al calendario, rispondendo "non posso collegarmi".
    assert outlook.CALENDAR_INTENT_RE.search("dici che riunioni un programma domani")
    assert outlook.CALENDAR_INTENT_RE.search("impegni di domani")
    assert outlook.CALENDAR_INTENT_RE.search("domani ho riunioni")


def _make_event(subject="Sync settimanale", hour=10, minute=0, location=""):
    start = dt.datetime(2026, 9, 16, hour, minute)
    return outlook.CalendarEvent(
        subject=subject,
        start=start,
        end=start + dt.timedelta(minutes=30),
        location=location,
        entry_id=f"{subject}-{start.isoformat()}",
    )


def test_format_events_empty_list():
    assert "Nessun" in outlook.format_events([], voice=False)
    assert "Signore" in outlook.format_events([], voice=True)


def test_format_events_voice_lists_subject_and_time():
    events = [_make_event(subject="Standup", hour=9, minute=30)]
    text = outlook.format_events(events, voice=True)
    assert "Standup" in text and "09:30" in text and "Signore" in text


def test_format_events_text_includes_location_when_present():
    events = [_make_event(subject="Kickoff", hour=15, minute=0, location="Sala A")]
    text = outlook.format_events(events, voice=False)
    assert "Kickoff" in text and "Sala A" in text and "15:00" in text


def test_format_events_day_label_domani():
    events = [_make_event(subject="Standup", hour=9, minute=30)]
    voice = outlook.format_events(events, voice=True, day="domani")
    text = outlook.format_events([], voice=False, day="domani")
    assert "domani" in voice
    assert "domani" in text


def test_format_event_reminder_voice_and_text():
    event = _make_event(subject="Call cliente", hour=11, minute=45, location="Teams")
    voice = outlook.format_event_reminder(event, voice=True)
    text = outlook.format_event_reminder(event, voice=False)
    assert "Call cliente" in voice and "Signore" in voice
    assert "Call cliente" in text and "11:45" in text and "Teams" in text


def test_com_time_to_datetime_strips_com_type():
    class _FakeComTime:
        year, month, day, hour, minute, second = 2026, 9, 16, 14, 30, 0

    result = outlook._com_time_to_datetime(_FakeComTime())
    assert result == dt.datetime(2026, 9, 16, 14, 30, 0)
