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
