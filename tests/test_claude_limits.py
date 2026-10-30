import json

from core import claude_limits
from core import claude_statusline

LIMITS = {"five_hour": {"used_percentage": 23.5, "resets_at": 1_800_000_000},
          "seven_day": {"used_percentage": 41, "resets_at": "2026-11-05T09:00:00Z"}}


def test_statusline_saves_limits_and_prints_short_line(tmp_path):
    target = tmp_path / ".claude-limits.json"
    line = claude_statusline.save({"rate_limits": LIMITS}, target, now=1_800_000_000.0)
    assert line == "5h 24% · 7g 41%"
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["at"] == 1_800_000_000.0 and saved["five_hour"]["used_percentage"] == 23.5


def test_statusline_keeps_previous_value_without_rate_limits(tmp_path):
    target = tmp_path / ".claude-limits.json"
    claude_statusline.save({"rate_limits": LIMITS}, target, now=1_800_000_000.0)
    assert claude_statusline.save({"model": "x"}, target, now=1_800_003_600.0) == ""
    assert json.loads(target.read_text(encoding="utf-8"))["at"] == 1_800_000_000.0


def test_read_reports_percent_reset_and_staleness(tmp_path, monkeypatch):
    target = tmp_path / ".claude-limits.json"
    monkeypatch.setattr(claude_limits, "FILE", target)
    claude_statusline.save({"rate_limits": LIMITS}, target, now=1_800_000_000.0)
    fresh = claude_limits.read(now=1_800_000_000.0 + 60)
    assert fresh["available"] and not fresh["stale"]
    assert fresh["windows"]["5h"]["percent"] == 23.5
    assert fresh["windows"]["5h"]["resets_at"]  # epoch convertito in ISO locale
    assert fresh["windows"]["7g"]["resets_at"] == "2026-11-05T09:00:00Z"
    assert claude_limits.read(now=1_800_000_000.0 + 7 * 3600)["stale"]


def test_read_without_file_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_limits, "FILE", tmp_path / "missing.json")
    data = claude_limits.read()
    assert data["available"] is False and data["windows"] == {}
