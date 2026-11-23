from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from suite.git import check_app, get_remote_url
from suite.models import App


def git(path: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Suite Test",
            "GIT_AUTHOR_EMAIL": "suite@example.com",
            "GIT_COMMITTER_NAME": "Suite Test",
            "GIT_COMMITTER_EMAIL": "suite@example.com",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
    )
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def commit_file(path: Path, contents: str, message: str) -> None:
    (path / "file.txt").write_text(contents, encoding="utf-8")
    git(path, "add", "file.txt")
    git(path, "commit", "-m", message)


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))

    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-b", "main")
    commit_file(seed, "one\n", "initial")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "main")

    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(origin), str(clone))
    return origin, clone


def test_clean_up_to_date_repository(repositories: tuple[Path, Path]) -> None:
    _, clone = repositories

    result = check_app(App(name="demo", local_dir=clone))

    assert result.state == "ok"
    assert result.changes == 0
    assert result.behind == 0
    assert result.ahead == 0
    assert result.branch == "main"
    assert result.upstream == "origin/main"


def test_uncommitted_changes_are_counted(
    repositories: tuple[Path, Path],
) -> None:
    _, clone = repositories
    (clone / "file.txt").write_text("changed\n", encoding="utf-8")
    (clone / "untracked.txt").write_text("new\n", encoding="utf-8")

    result = check_app(App(name="demo", local_dir=clone))

    assert result.state == "ok"
    assert result.changes == 2


def test_commits_to_pull_require_fetch(
    repositories: tuple[Path, Path], tmp_path: Path
) -> None:
    origin, clone = repositories
    other = tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(other))
    commit_file(other, "remote change\n", "remote change")
    git(other, "push", "origin", "main")

    stale = check_app(App(name="demo", local_dir=clone), fetch=False)
    assert stale.behind == 0

    fetched = check_app(App(name="demo", local_dir=clone), fetch=True)
    assert fetched.behind == 1
    assert fetched.ahead == 0

    commit_file(clone, "local change\n", "local change")
    local = check_app(App(name="demo", local_dir=clone), fetch=False)
    assert local.behind == 1
    assert local.ahead == 1


def test_remote_url_prefers_origin(repositories: tuple[Path, Path]) -> None:
    origin, clone = repositories
    git(clone, "remote", "add", "other", "git@example.com:other.git")

    assert get_remote_url(clone) == str(origin)


def test_remote_url_without_remotes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")

    assert get_remote_url(repo) is None


def test_missing_directory(tmp_path: Path) -> None:
    result = check_app(
        App(name="demo", local_dir=tmp_path / "nope"), fetch=False
    )

    assert result.state == "missing"
    assert result.has_problem


def test_not_a_git_repository(tmp_path: Path) -> None:
    result = check_app(App(name="demo", local_dir=tmp_path), fetch=False)

    assert result.state == "not-git"
    assert result.has_problem


def test_repository_without_upstream(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    commit_file(repo, "one\n", "initial")

    result = check_app(App(name="demo", local_dir=repo), fetch=False)

    assert result.state == "ok"
    assert result.upstream is None
    assert result.branch == "main"
