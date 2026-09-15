from core.web_bridge import _strip_wake_word


def test_wake_word_present_strips_prefix():
    assert _strip_wake_word("Jarvis apri chrome") == "apri chrome"


def test_wake_word_case_insensitive_and_mid_sentence():
    assert _strip_wake_word("ehi JARVIS, che ore sono") == "che ore sono"


def test_no_wake_word_is_ignored():
    assert _strip_wake_word("stavo giusto guardando la tv") is None


def test_wake_word_alone_is_ignored():
    assert _strip_wake_word("Jarvis") is None


def test_wake_word_followed_by_noise_word_is_ignored():
    assert _strip_wake_word("jarvis eh") is None


def test_substring_of_wake_word_does_not_match():
    assert _strip_wake_word("jarvisone apri chrome") is None


def test_wake_word_phonetic_variant_yarvis_matches():
    # Osservato dal vivo (2026-09-15): whisper in italiano puo' trascrivere
    # "Jarvis" foneticamente come "YARVIS" - senza questa variante il
    # comando sarebbe stato scartato in silenzio nonostante fosse valido.
    assert _strip_wake_word("YARVIS leggi l'ultima mail") == "leggi l'ultima mail"


def test_wake_word_phonetic_variant_giarvis_matches():
    assert _strip_wake_word("giarvis apri chrome") == "apri chrome"


def test_wake_word_unrelated_word_ending_in_arvis_does_not_match():
    assert _strip_wake_word("questo scarvis non esiste apri chrome") is None


def test_known_hallucination_phrase_is_ignored():
    assert _strip_wake_word("Il maggiordomo AI di Iron Man.") is None
    assert _strip_wake_word("Sottotitoli e revisione a cura di QTSS.") is None
    assert _strip_wake_word("Buon appetito!") is None


def test_wake_word_far_from_start_is_ignored():
    long_ramble = (
        "e male che va scendiamo ci ho contatto un po' la scendiamo cosi "
        "la pilliamo e poi arrivo jarvis apri chrome"
    )
    assert _strip_wake_word(long_ramble) is None


def test_wake_word_still_matches_with_short_lead_in():
    assert _strip_wake_word("ok, adesso jarvis apri chrome") == "apri chrome"
