from unittest.mock import patch

from core import win_focus


def test_bring_pid_to_foreground_bg_never_raises_on_bad_pid():
    """Un PID inesistente/gia' morto (finestra chiusa subito, app fallita ad
    avviarsi, ecc.) non deve mai far esplodere il thread in background —
    silenziosamente rinuncia a portare in primo piano."""
    thread_ref = {}
    orig_thread = __import__("threading").Thread

    def _capture_thread(*a, **k):
        t = orig_thread(*a, **k)
        thread_ref["t"] = t
        return t

    with patch("threading.Thread", side_effect=_capture_thread):
        win_focus.bring_pid_to_foreground_bg(999_999_999)  # PID quasi certamente inesistente

    thread_ref["t"].join(timeout=5)
    assert not thread_ref["t"].is_alive()


def test_bring_matching_to_foreground_bg_gives_up_when_nothing_matches():
    """Nessun processo con quella sottostringa in cmdline (profilo mai
    lanciato, gia' chiuso, ecc.) — deve arrendersi silenziosamente entro il
    timeout, non restare bloccato ne' sollevare."""
    thread_ref = {}
    orig_thread = __import__("threading").Thread

    def _capture_thread(*a, **k):
        t = orig_thread(*a, **k)
        thread_ref["t"] = t
        return t

    with patch("threading.Thread", side_effect=_capture_thread):
        win_focus.bring_matching_to_foreground_bg("marcatore-che-non-esiste-di-sicuro-xyz", timeout=0.3)

    thread_ref["t"].join(timeout=5)
    assert not thread_ref["t"].is_alive()


def test_find_window_for_pids_returns_none_when_no_match():
    assert win_focus.find_window_for_pids({999_999_999}, timeout=0.2) is None
