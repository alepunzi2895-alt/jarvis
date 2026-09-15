from core import outlook


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


# Nota: _fetch_recent_sync() non ha un test a unit dedicato — tocca COM/
# Outlook desktop reale (hardware/software esterno), stesso stile gia' in
# uso nel repo per core/voice/camera.py (webcam): verificato dal vivo
# invece che con un mock fragile dell'import di win32com.client.
