from unittest.mock import patch

from core import remote_status


def test_matches_github_and_vercel_by_repo_field():
    repos = [{"name": "-VMScout", "full_name": "u/-VMScout"}, {"name": "unrelated", "full_name": "u/unrelated"}]
    projects = [{"name": "vmscout", "repo": "-VMScout"}]

    with patch("core.remote_status.github_status.list_repos", return_value=repos), \
         patch("core.remote_status.vercel_status.list_projects", return_value=projects):
        data = remote_status.build_remote_status()

    entries = {e["github"]["name"]: e["vercel"] for e in data["entries"]}
    assert entries["-VMScout"]["name"] == "vmscout"
    assert entries["unrelated"] is None


def test_vercel_project_without_matching_repo_still_included():
    with patch("core.remote_status.github_status.list_repos", return_value=[]), \
         patch("core.remote_status.vercel_status.list_projects", return_value=[{"name": "orphan", "repo": "gone"}]):
        data = remote_status.build_remote_status()

    assert len(data["entries"]) == 1
    assert data["entries"][0]["github"] is None
    assert data["entries"][0]["vercel"]["name"] == "orphan"


def test_empty_sources_produce_empty_entries():
    with patch("core.remote_status.github_status.list_repos", return_value=[]), \
         patch("core.remote_status.vercel_status.list_projects", return_value=[]):
        data = remote_status.build_remote_status()

    assert data == {"entries": []}
