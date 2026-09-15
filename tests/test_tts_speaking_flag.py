from core.voice import tts


def test_set_speaking_noop_when_turso_disabled(monkeypatch):
    monkeypatch.setattr(tts.turso, "ENABLED", False)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda *a, **k: calls.append((a, k)))
    tts._set_speaking(True)
    assert calls == []


def test_set_speaking_writes_upsert_when_enabled(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", True)  # salta il CREATE TABLE
    monkeypatch.setattr(tts.turso, "ENABLED", True)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda sql, args=None: calls.append((sql, args)))

    tts._set_speaking(True)

    assert len(calls) == 1
    sql, args = calls[0]
    assert "runtime_flags" in sql
    assert "ON CONFLICT" in sql
    assert args == ["1"]


def test_set_speaking_false_writes_zero(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", True)
    monkeypatch.setattr(tts.turso, "ENABLED", True)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda sql, args=None: calls.append(args))

    tts._set_speaking(False)

    assert calls == [["0"]]


def test_set_speaking_swallows_turso_errors(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", True)
    monkeypatch.setattr(tts.turso, "ENABLED", True)

    def _boom(sql, args=None):
        raise RuntimeError("rete giu'")

    monkeypatch.setattr(tts.turso, "execute", _boom)
    tts._set_speaking(True)  # non deve sollevare


def test_bootstrap_runs_create_table_once(monkeypatch):
    monkeypatch.setattr(tts, "_speaking_flag_bootstrapped", False)
    calls = []
    monkeypatch.setattr(tts.turso, "execute", lambda sql, args=None: calls.append(sql))

    tts._bootstrap_speaking_flag()
    tts._bootstrap_speaking_flag()

    assert len(calls) == 1
    assert "CREATE TABLE IF NOT EXISTS runtime_flags" in calls[0]
