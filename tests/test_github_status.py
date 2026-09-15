from unittest.mock import MagicMock, patch

from core import github_status


def _fake_response(json_data):
    r = MagicMock()
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


def test_list_repos_empty_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert github_status.list_repos() == []


def test_list_repos_filters_archived_and_forks(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    repos_response = _fake_response([
        {"name": "a", "full_name": "u/a", "archived": True, "default_branch": "main"},
        {"name": "b", "full_name": "u/b", "fork": True, "default_branch": "main"},
        {"name": "c", "full_name": "u/c", "default_branch": "main", "private": False, "html_url": "https://x"},
    ])
    commit_response = _fake_response({
        "sha": "abc1234567",
        "commit": {"message": "fix: bug\n\nlong body", "author": {"date": "2026-09-15T10:00:00Z"}},
    })
    with patch("core.github_status.requests.get", side_effect=[repos_response, commit_response]):
        repos = github_status.list_repos()

    assert len(repos) == 1
    assert repos[0]["name"] == "c"
    assert repos[0]["last_commit"] == {"sha": "abc1234", "message": "fix: bug", "date": "2026-09-15T10:00:00Z"}


def test_list_repos_includes_forks_when_asked(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    repos_response = _fake_response([
        {"name": "b", "full_name": "u/b", "fork": True, "default_branch": "main"},
    ])
    commit_response = _fake_response({"sha": "1234567", "commit": {"message": "m", "author": {"date": "d"}}})
    with patch("core.github_status.requests.get", side_effect=[repos_response, commit_response]):
        repos = github_status.list_repos(include_forks=True)

    assert len(repos) == 1
    assert repos[0]["name"] == "b"


def test_list_repos_respects_max_repos(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    many = [{"name": f"r{i}", "full_name": f"u/r{i}", "default_branch": None} for i in range(10)]
    with patch("core.github_status.requests.get", return_value=_fake_response(many)):
        repos = github_status.list_repos(max_repos=3)

    assert len(repos) == 3


def test_list_repos_swallows_network_errors(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    import requests

    with patch("core.github_status.requests.get", side_effect=requests.RequestException("boom")):
        assert github_status.list_repos() == []


def test_missing_last_commit_does_not_crash_summary(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    repos_response = _fake_response([{"name": "c", "full_name": "u/c", "default_branch": "main"}])
    import requests

    with patch("core.github_status.requests.get", side_effect=[repos_response, requests.RequestException("boom")]):
        repos = github_status.list_repos()

    assert repos[0]["last_commit"] is None
