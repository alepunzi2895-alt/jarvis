import pytest


@pytest.fixture(autouse=True)
def _isolate_personal_memory_and_tradepilot(monkeypatch, tmp_path):
    monkeypatch.setattr('core.conversation_memory.DB', tmp_path / 'memory.sqlite3')
    monkeypatch.setattr('core.coding_tasks.DB', tmp_path / 'coding.sqlite3')
    monkeypatch.setattr('core.tradepilot.DB', tmp_path / 'tradepilot.sqlite3')
    monkeypatch.setattr('core.tradepilot.CONFIG', tmp_path / 'tradepilot.json')
    monkeypatch.setattr('core.tradepilot._cache', {'at': 0, 'value': None, 'key': ''})
    monkeypatch.setattr('core.azure_devops.CONFIG', tmp_path / 'azure-devops.json')
    monkeypatch.setattr('core.azure_devops._cache', {'at': 0, 'value': None, 'key': ''})
    monkeypatch.setattr('core.agent_sessions.CLAUDE_DIR', tmp_path / 'claude-projects')
    monkeypatch.setattr('core.agent_sessions.CODEX_DIR', tmp_path / 'codex-sessions')
    monkeypatch.setattr('core.voice.tts.VOICE_OVERRIDE', tmp_path / 'tts-voice.json')
    monkeypatch.setattr('core.voice.tts._override', {'mtime': None, 'data': {}})


@pytest.fixture(autouse=True)
def _disable_real_turso(monkeypatch):
    """Nessun test deve toccare la Turso vera — questa macchina di sviluppo ha
    credenziali reali in .env, quindi senza questo i test che passano da
    core/intents.py o core/brain.py scriverebbero dati di test nel second
    brain di produzione."""
    monkeypatch.setattr("core.turso.ENABLED", False)


@pytest.fixture(autouse=True)
def _reset_brain_bootstrap(monkeypatch):
    """_bootstrap() usa un flag a livello di modulo per non ricreare le tabelle
    ad ogni chiamata — va resettato tra un test e l'altro, altrimenti un test
    che la settano a True "nasconde" il bootstrap ai test successivi."""
    monkeypatch.setattr("core.brain._bootstrapped", False, raising=False)


@pytest.fixture(autouse=True)
def _no_real_obsidian_vault(monkeypatch):
    """core.brain._vault() cachea il risultato a livello di modulo e, se
    JARVIS_VAULT_PATH punta al vault vero (come nel .env di sviluppo di
    Alessandro), scriverebbe note reali dentro il suo Obsidian durante i test.
    Forzato a None per l'intera sessione di test."""
    monkeypatch.delenv("JARVIS_VAULT_PATH", raising=False)
    monkeypatch.setattr("core.brain._vault_checked", False, raising=False)
    monkeypatch.setattr("core.brain._vault_instance", None, raising=False)


@pytest.fixture(autouse=True)
def _reset_weather_cache(monkeypatch):
    monkeypatch.setattr("core.weather._cache", {"line": None, "ts": 0.0, "ok": False}, raising=False)


@pytest.fixture(autouse=True)
def _reset_project_snapshot(monkeypatch):
    monkeypatch.setattr("core.project_status._snapshot_cache", {"key": None, "ts": 0.0, "values": []})
