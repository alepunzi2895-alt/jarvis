from datetime import datetime
import json

import pytest

from core import iveco


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 10, 19, 9, 30), datetime(2026, 10, 16)),  # lunedi' -> venerdi'
    (datetime(2026, 10, 16, 9, 30), datetime(2026, 10, 15)),  # venerdi' -> giovedi'
    (datetime(2026, 10, 18, 12, 0), datetime(2026, 10, 16)),  # domenica -> venerdi'
])
def test_window_starts_on_previous_working_day(now, expected):
    assert iveco.window_start(now) == expected


def test_next_recap_skips_weekend_and_past_times(monkeypatch):
    monkeypatch.setattr(iveco, "RECAP_TIME", "09:30")
    assert iveco.next_recap_at(datetime(2026, 10, 16, 8, 0)) == datetime(2026, 10, 16, 9, 30)
    assert iveco.next_recap_at(datetime(2026, 10, 16, 9, 30)) == datetime(2026, 10, 19, 9, 30)
    assert iveco.next_recap_at(datetime(2026, 10, 17, 7, 0)) == datetime(2026, 10, 19, 9, 30)


def test_gather_survives_every_source_failing(monkeypatch):
    def broken(*args):
        raise RuntimeError("giu'")
    for name in ("_job_runs", "_workspace_changes", "_dashboard_changes", "_apps", "_deploys", "_mail", "_meetings"):
        monkeypatch.setattr(iveco, name, broken)
    data = iveco.gather(datetime(2026, 10, 16, 9, 30))
    assert data["since"] == "2026-10-15 00:00"
    assert data["facts"] == {}
    assert data["sources"]["mail"] == "non disponibile (RuntimeError)"
    assert data["sources"]["teams"] == "non collegato"


def test_build_recap_saves_summary_and_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(iveco, "RECAP_FILE", tmp_path / ".iveco-recap.json")
    monkeypatch.setattr(iveco, "gather", lambda now=None: dict(now="2026-10-16 09:30", since="2026-10-15 00:00",
                                                               facts={"mail": []}, sources={"mail": "ok"}))
    monkeypatch.setattr(iveco, "summarize", lambda data: "Fatto: nulla di rilevante")
    record = iveco.build_recap()
    assert record["text"] == "Fatto: nulla di rilevante"
    assert iveco.latest() == record
    assert json.loads((tmp_path / ".iveco-recap.json").read_text(encoding="utf-8"))["since"] == "2026-10-15 00:00"


def test_iso_after_handles_utc_and_bad_values():
    since = datetime(2026, 10, 15)
    assert iveco._iso_after("2026-10-16T08:00:00Z", since)
    assert not iveco._iso_after("2026-10-01T08:00:00Z", since)
    assert not iveco._iso_after(None, since)
    assert not iveco._iso_after("ieri", since)
