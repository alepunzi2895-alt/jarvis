import pytest


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
