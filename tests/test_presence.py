from core import presence


def _tracker_with_mocks(monkeypatch, recognized_sequence):
    """recognized_sequence: lista di bool, uno per ogni chiamata a check().
    True = un frame con Alessandro riconosciuto, False = nessuno/sconosciuto."""
    it = iter(recognized_sequence)

    monkeypatch.setattr(presence.face_id, "is_enrolled", lambda: True)
    monkeypatch.setattr(presence.camera, "capture_frame_raw", lambda: object())
    monkeypatch.setattr(
        presence.face_id, "recognize", lambda frame: ("alessandro", 10.0) if next(it) else (None, -1.0)
    )
    return presence.PresenceTracker()


def test_no_greeting_when_not_enrolled(monkeypatch):
    monkeypatch.setattr(presence.face_id, "is_enrolled", lambda: False)
    tracker = presence.PresenceTracker()
    assert tracker.check(now=0) is None


def test_no_greeting_when_camera_unavailable(monkeypatch):
    monkeypatch.setattr(presence.face_id, "is_enrolled", lambda: True)
    monkeypatch.setattr(presence.camera, "capture_frame_raw", lambda: None)
    tracker = presence.PresenceTracker()
    assert tracker.check(now=0) is None


def test_transition_to_present_greets(monkeypatch):
    tracker = _tracker_with_mocks(monkeypatch, [True])
    greeting = tracker.check(now=0)
    assert greeting in presence._GREETINGS


def test_staying_present_does_not_regreet(monkeypatch):
    tracker = _tracker_with_mocks(monkeypatch, [True, True, True])
    first = tracker.check(now=0)
    second = tracker.check(now=1)
    third = tracker.check(now=2)
    assert first is not None
    assert second is None
    assert third is None


def test_single_dropped_frame_does_not_trigger_absence(monkeypatch):
    # presente, un frame perso, poi di nuovo presente: non deve rigreet-are
    # (streak di assenza sotto soglia, considerato ancora "presente").
    tracker = _tracker_with_mocks(monkeypatch, [True, False, True])
    first = tracker.check(now=0)
    second = tracker.check(now=1)
    third = tracker.check(now=2)
    assert first is not None
    assert second is None
    assert third is None


def test_real_absence_then_return_greets_again_after_cooldown(monkeypatch):
    sequence = [True] + [False] * presence._ABSENCE_STREAK + [True]
    tracker = _tracker_with_mocks(monkeypatch, sequence)
    results = [tracker.check(now=i * (presence.COOLDOWN_SEC + 1)) for i in range(len(sequence))]
    assert results[0] is not None  # prima comparsa
    assert all(r is None for r in results[1:-1])  # assenza
    assert results[-1] is not None  # ritorno, cooldown scaduto (now avanzato apposta)


def test_return_within_cooldown_does_not_regreet(monkeypatch):
    sequence = [True] + [False] * presence._ABSENCE_STREAK + [True]
    tracker = _tracker_with_mocks(monkeypatch, sequence)
    results = [tracker.check(now=i) for i in range(len(sequence))]  # now quasi fermo: dentro il cooldown
    assert results[0] is not None
    assert all(r is None for r in results[1:])
