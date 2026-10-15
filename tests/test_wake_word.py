import threading
import time

import pytest

wake_word = pytest.importorskip("core.voice.wake_word")


class _Stream:
    opened = 0
    closed = 0

    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        _Stream.opened += 1
        return self

    def __exit__(self, *exc):
        _Stream.closed += 1


class _Model:
    def __init__(self, **kwargs):
        pass

    def reset(self):
        pass


def test_wait_releases_microphone_when_console_closes(monkeypatch):
    monkeypatch.setattr(wake_word.sd, "InputStream", _Stream)
    monkeypatch.setattr(wake_word, "Model", _Model)
    monkeypatch.setattr(wake_word, "resolve_input_device", lambda: None)
    listener = wake_word.WakeWordListener()
    console_open = threading.Event()
    console_open.set()
    threading.Timer(0.2, console_open.clear).start()
    started = time.monotonic()
    assert listener.wait(cancel_event=threading.Event(), active=console_open.is_set) is False
    assert time.monotonic() - started < 2
    assert _Stream.opened == _Stream.closed == 1
