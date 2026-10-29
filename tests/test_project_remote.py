import subprocess

import pytest

from core import project_status, projects


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]})


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(origin), str(local))
    (local / "a.txt").write_text("1", encoding="utf-8")
    _git(local, "add", "a.txt")
    _git(local, "commit", "-q", "-m", "primo")
    _git(local, "push", "-q", "origin", "main")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    return local, other


def test_remote_commit_pushed_from_other_device_is_flagged(repos):
    local, other = repos
    (other / "b.txt").write_text("2", encoding="utf-8")
    _git(other, "add", "b.txt")
    _git(other, "commit", "-q", "-m", "da telefono")
    _git(other, "push", "-q", "origin", "main")

    status = project_status.ProjectStatus("whitesoul", "White Soul", str(local), configured=True, branch="main")
    project_status._check_remote(status, str(local))

    assert status.remote_ahead is True
    assert status.remote_commit and len(status.remote_commit) == 7


def test_up_to_date_repo_is_not_flagged(repos):
    local, _ = repos
    status = project_status.ProjectStatus("whitesoul", "White Soul", str(local), configured=True, branch="main")
    project_status._check_remote(status, str(local))
    assert status.remote_ahead is False


def test_git_read_refuses_write_commands():
    with pytest.raises(ValueError):
        projects.git_read(".", "push", "origin", "main")
    with pytest.raises(ValueError):
        projects.git_read(".", "cat-file", "-e", "not-a-hash")
