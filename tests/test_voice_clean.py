from core.voice.tts import clean_for_speech


def test_ids_and_codes_are_not_read_out():
    text = "Ho creato il task 3f2a9c1e-8b7d-4e21-9a6f-0c1d2e3f4a5b, ok."
    assert clean_for_speech(text) == "Ho creato il task un codice, ok."


def test_long_numbers_and_urls_and_paths_are_replaced():
    assert clean_for_speech("Chat 123456789 pronta") == "Chat un numero lungo pronta"
    assert clean_for_speech("Vedi https://example.com/a/b?x=1 adesso") == "Vedi un link adesso"
    assert clean_for_speech(r"Il file C:\Users\f45038c\note.md è pronto") == "Il file un percorso è pronto"


def test_dates_counts_and_words_are_kept():
    text = "Il 2026-10-29 hai 12 mail e Iveco è in ritardo."
    assert clean_for_speech(text) == text


def test_markdown_links_keep_their_label():
    assert clean_for_speech("Apri [la dashboard](https://x.y)") == "Apri la dashboard"
