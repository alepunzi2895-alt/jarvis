from unittest.mock import MagicMock, patch

import requests

from core import vercel_status


def _fake_response(json_data):
    r = MagicMock()
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


def test_list_projects_empty_without_token(monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    assert vercel_status.list_projects() == []


def test_list_projects_summarizes_latest_deployment(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "vcp_test")
    response = _fake_response({
        "projects": [
            {
                "name": "jarvis-dashboard",
                "link": {"repo": "jarvis"},
                "latestDeployments": [
                    {"url": "jarvis-dashboard-abc.vercel.app", "readyState": "READY", "createdAt": 1700000000000},
                ],
            }
        ]
    })
    with patch("core.vercel_status.requests.get", return_value=response):
        projects = vercel_status.list_projects()

    assert projects == [{
        "name": "jarvis-dashboard",
        "url": "https://jarvis-dashboard-abc.vercel.app",
        "state": "READY",
        "updated_at": 1700000000000,
        "repo": "jarvis",
    }]


def test_list_projects_handles_missing_deployments(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "vcp_test")
    response = _fake_response({"projects": [{"name": "empty-project", "link": None, "latestDeployments": []}]})
    with patch("core.vercel_status.requests.get", return_value=response):
        projects = vercel_status.list_projects()

    assert projects == [{"name": "empty-project", "url": None, "state": None, "updated_at": None, "repo": None}]


def test_list_projects_swallows_network_errors(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "vcp_test")
    with patch("core.vercel_status.requests.get", side_effect=requests.RequestException("boom")):
        assert vercel_status.list_projects() == []


def test_list_projects_passes_team_id_when_set(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "vcp_test")
    monkeypatch.setenv("VERCEL_TEAM_ID", "team_123")
    response = _fake_response({"projects": []})
    with patch("core.vercel_status.requests.get", return_value=response) as get:
        vercel_status.list_projects()

    assert get.call_args.kwargs["params"]["teamId"] == "team_123"
