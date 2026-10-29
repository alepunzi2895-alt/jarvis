import asyncio

from core import work_apps


class FakeAgent:
    def __init__(self, open_urls=()):
        self.open_urls, self.opened = set(open_urls), []

    def is_open(self, url):
        return url in self.open_urls

    async def open(self, url, foreground=True):
        self.opened.append((url, foreground))
        return f"Aperto {url}."


def _run(agent, apps, monkeypatch, desktop=(), force=False):
    monkeypatch.setattr(work_apps, "desktop_running", lambda app: app in desktop)
    monkeypatch.setattr(work_apps, "web_urls", lambda: {"teams": "T", "outlook": "O", "servicenow": "S"})
    monkeypatch.setattr("core.browser.get_agent", lambda: agent)
    return asyncio.run(work_apps.ensure_open(apps, force=force))


def test_desktop_app_is_used_and_web_not_opened(monkeypatch):
    agent = FakeAgent()
    results = _run(agent, ["teams", "outlook"], monkeypatch, desktop={"teams"})
    assert [r["state"] for r in results] == ["desktop", "aperto ora"]
    assert agent.opened == [("O", False)]


def test_already_open_page_is_left_alone(monkeypatch):
    agent = FakeAgent(open_urls={"S"})
    results = _run(agent, ["servicenow"], monkeypatch)
    assert results[0]["state"] == "aperto" and agent.opened == []


def test_retry_cooldown_and_force(monkeypatch):
    agent = FakeAgent()
    _run(agent, ["servicenow"], monkeypatch)
    assert _run(agent, ["servicenow"], monkeypatch)[0]["state"] == "recente"
    _run(agent, ["servicenow"], monkeypatch, force=True)
    assert agent.opened == [("S", False), ("S", True)]


def test_iveco_question_detection():
    assert work_apps.IVECO_RE.search("come va il deploy IVECO?")
    assert work_apps.IVECO_RE.search("chiedi a ivg agent")
    assert not work_apps.IVECO_RE.search("che tempo fa")
