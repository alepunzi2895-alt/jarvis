from datetime import datetime
import json

from core import feed, project_insights, projects


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_insights, "CONVERSATIONS_FILE", tmp_path / "conv.jsonl")
    monkeypatch.setattr(project_insights, "INSIGHTS_FILE", tmp_path / "insights.json")
    monkeypatch.setattr(project_insights, "NOTES_DIR", tmp_path)
    monkeypatch.setattr(feed, "FEED", tmp_path / "feed.jsonl")
    (tmp_path / "whitesoulibiza.md").write_text("# White Soul Ibiza\n\n## Stato\nSito statico.\n", encoding="utf-8")
    catalog = [projects.Project("whitesoulibiza", "White Soul Ibiza", None, "whitesoulibiza.md"),
               projects.Project("auraibiza", "AURA Ibiza", None, "")]
    monkeypatch.setattr(projects, "catalog", lambda: catalog)
    return catalog


def _write_turn(tmp_path, at, prompt, answer):
    with (tmp_path / "conv.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(at=at, source="dashboard", prompt=prompt, answer=answer)) + "\n")


def test_update_saves_insights_and_note_after_idle(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _write_turn(tmp_path, "2026-10-28 11:06:10", "entro fine mese vorrei chiudere whitesoul su Aruba",
                "Tenga separati manutenzione e Instagram.")
    asked = []

    def ask(payload):
        asked.append(payload)
        return {"whitesoulibiza": dict(summary="Consegna entro fine mese.", next_steps=["Migrare il dominio su Aruba"],
                                       advice=["Canone manutenzione separato da Instagram"]),
                "inventato": dict(summary="x", next_steps=[], advice=[])}

    monkeypatch.setattr(project_insights, "_ask", ask)
    # Conversazione ancora in corso: nessuna chiamata.
    assert project_insights.update(datetime(2026, 10, 28, 11, 8)) == []
    assert not asked
    assert project_insights.update(datetime(2026, 10, 28, 11, 20)) == ["whitesoulibiza"]
    assert [p["key"] for p in asked[0]["projects"]] == ["whitesoulibiza"]
    state = project_insights.latest()
    assert state["processed_until"] == "2026-10-28 11:06:10"
    assert state["projects"]["whitesoulibiza"]["next_steps"] == ["Migrare il dominio su Aruba"]
    note = (tmp_path / "whitesoulibiza.md").read_text(encoding="utf-8")
    assert "## Stato\nSito statico." in note and "- Migrare il dominio su Aruba" in note
    # Seconda volta: la sezione viene sostituita, non duplicata.
    _write_turn(tmp_path, "2026-10-28 12:00:00", "whitesoul: dominio fatto", "Bene.")
    monkeypatch.setattr(project_insights, "_ask", lambda payload: {"whitesoulibiza": dict(
        summary="Dominio pronto.", next_steps=["Sostituire le foto Unsplash"], advice=[])})
    project_insights.update(datetime(2026, 10, 28, 12, 30))
    note = (tmp_path / "whitesoulibiza.md").read_text(encoding="utf-8")
    assert note.count(project_insights.SECTION) == 1 and "Aruba" not in note.split(project_insights.SECTION)[1]


def test_conversation_without_projects_skips_model(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _write_turn(tmp_path, "2026-10-28 11:01:05", "come vanno i progetti?", "AURA ha 2 file modificati.")
    monkeypatch.setattr(project_insights, "_ask", lambda payload: (_ for _ in ()).throw(AssertionError))
    assert project_insights.update(datetime(2026, 10, 28, 12, 0)) == []
    assert project_insights.latest()["processed_until"] == "2026-10-28 11:01:05"


def test_turns_read_telegram_answers_and_voice_but_not_reminders(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    rows = [dict(id="1", at="2026-10-28 09:51:58", source="telegram", prompt="", text="Tra 15 minuti: Daily"),
            dict(id="2", at="2026-10-28 10:00:00", source="telegram_in", prompt="prezzo per aura?", text=""),
            dict(id="3", at="2026-10-28 10:00:20", source="telegram", prompt="", text="Tra 300 e 800 euro."),
            dict(id="4", at="2026-10-28 10:05:00", source="voce", prompt="e whitesoul?", text="Da chiudere.")]
    (tmp_path / "feed.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    turns = project_insights._turns("")
    assert [(t["who"], t["text"]) for t in turns] == [
        ("Alessandro", "prezzo per aura?"), ("JARVIS", "Tra 300 e 800 euro."),
        ("Alessandro", "e whitesoul?"), ("JARVIS", "Da chiudere.")]


def test_aliases_match_short_names(monkeypatch, tmp_path):
    catalog = _setup(monkeypatch, tmp_path)
    turns = [dict(who="Alessandro", text="chiudo White Soul e poi Aura")]
    assert [p.key for p in project_insights.mentioned(turns, catalog)] == ["whitesoulibiza", "auraibiza"]
    assert project_insights.mentioned([dict(who="Alessandro", text="whitelist")], catalog) == []


def test_record_ignores_empty_prompt(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    project_insights.record("dashboard", "  ", "x")
    project_insights.record("dashboard", "ciao", "risposta")
    lines = (tmp_path / "conv.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["prompt"] == "ciao"


def test_wake_word_is_not_the_jarvis_project_and_labels_have_short_names():
    catalog = [projects.Project("jarvis", "JARVIS — stato progetto", None, "jarvis.md"),
               projects.Project("tradepilot-ai", "TradePilot — integrazione JARVIS", None, "")]
    assert project_insights.mentioned([dict(who="Alessandro", text="Jarvis, che ore sono?")], catalog) == []
    found = project_insights.mentioned([dict(who="Alessandro", text="Jarvis, come va TradePilot? e jarvis?")], catalog)
    assert [p.key for p in found] == ["jarvis", "tradepilot-ai"]
