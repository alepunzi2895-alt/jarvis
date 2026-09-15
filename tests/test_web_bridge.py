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
