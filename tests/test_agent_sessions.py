import json
import os
import time

from core import agent_sessions, coding_tasks


def _write(path, records, age_sec=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    stamp = time.time() - age_sec
    os.utime(path, (stamp, stamp))


def _claude(cwd, prompt, answer, stop="end_turn"):
    return [
        {"type": "user", "cwd": cwd, "gitBranch": "main", "entrypoint": "claude-vscode",
         "message": {"role": "user", "content": prompt}},
        {"type": "ai-title", "aiTitle": "Ricerche interrotte"},
        {"type": "last-prompt", "lastPrompt": prompt},
        {"type": "assistant", "cwd": cwd, "message": {"role": "assistant", "stop_reason": stop,
                                                      "content": [{"type": "text", "text": answer}]}},
    ]


def test_reads_claude_and_codex_sessions_newest_first():
    _write(agent_sessions.CLAUDE_DIR / "C--tradepilot" / "11111111-1111-1111-1111-111111111111.jsonl",
           _claude(r"C:\Users\me\Downloads\tradepilot-ai", "implementa le fasi", "Fase 1 completata."), age_sec=600)
    _write(agent_sessions.CODEX_DIR / "2026" / "10" / "14" / "rollout-2026-10-14T09-44-33-22222222-2222-2222-2222-222222222222.jsonl", [
        {"type": "session_meta", "payload": {"cwd": r"C:\Users\me\Downloads\jarvis", "originator": "Codex Desktop"}},
        {"type": "event_msg", "payload": {"type": "task_started"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "sistema il meteo"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "Sto leggendo app.js"}},
    ], age_sec=30)
    sessions = agent_sessions.recent_sessions()
    assert [(s["provider"], s["project"], s["state"]) for s in sessions] == [
        ("codex", "jarvis", "al lavoro"), ("claude", "tradepilot-ai", "in attesa di Alessandro")]
    claude = sessions[1]
    assert claude["title"] == "Ricerche interrotte" and claude["client"] == "claude-vscode"
    assert claude["last_prompt"] == "implementa le fasi" and claude["last_answer"] == "Fase 1 completata."
    assert claude["session_id"] == "11111111-1111-1111-1111-111111111111"


def test_old_temp_and_jarvis_sessions_are_skipped_and_secrets_hidden():
    _write(agent_sessions.CLAUDE_DIR / "old" / "a.jsonl", _claude(r"C:\x\old", "vecchio", "ok"), age_sec=7 * 3600)
    _write(agent_sessions.CLAUDE_DIR / "tmp" / "b.jsonl", _claude(r"C:\Users\me\AppData\Local\Temp\jarvis-coding-proof", "prova", "ok"))
    _write(agent_sessions.CLAUDE_DIR / "job" / "c.jsonl", _claude(r"C:\x\vmscout", "lavoro JARVIS", "ok"))
    _write(agent_sessions.CLAUDE_DIR / "live" / "d.jsonl",
           _claude(r"C:\x\aura", "usa il token sk_live_" + "A" * 40, "ok", stop="tool_use"), age_sec=900)
    sessions = agent_sessions.recent_sessions(exclude_ids={"c"})
    assert [s["project"] for s in sessions] == ["aura"]
    assert "A" * 40 not in sessions[0]["last_prompt"] and "[oscurato]" in sessions[0]["last_prompt"]
    assert sessions[0]["state"].startswith("ferma")


def test_coding_tasks_overview_adds_open_sessions():
    _write(agent_sessions.CLAUDE_DIR / "p" / "e.jsonl", _claude(r"C:\x\tradepilot-ai", "vai", "fatto"))
    data = coding_tasks.overview()
    assert data["jarvis_jobs"] == [] and data["open_sessions"][0]["project"] == "tradepilot-ai"
    assert coding_tasks.overview(project="vmscout")["open_sessions"] == []


def test_project_comes_from_session_start_not_last_cd():
    records = _claude(r"C:\x\jarvis", "inizio", "ok")
    records.append({"type": "user", "cwd": r"C:\x\jarvis\jarvis_voice\refs", "message": {"role": "user", "content": "ls"}})
    _write(agent_sessions.CLAUDE_DIR / "j" / "f.jsonl", records)
    assert agent_sessions.recent_sessions()[0]["project"] == "jarvis"
