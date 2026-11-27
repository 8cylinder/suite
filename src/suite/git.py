from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import SuiteError
from .models import App, CheckResult

CLONE_TIMEOUT = 300
FETCH_TIMEOUT = 60
GIT_TIMEOUT = 30
PULL_TIMEOUT = 300


def check_app(app: App, *, fetch: bool = True) -> CheckResult:
    """Inspect one application's repository."""
    try:
        return _check_app(app, fetch=fetch)
    except FileNotFoundError:
        return CheckResult(
            app=app,
            state="error",
            message="git is not installed or not on PATH",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            app=app, state="error", message="git command timed out"
        )
    except OSError as exc:
        return CheckResult(app=app, state="error", message=str(exc))


def _check_app(app: App, *, fetch: bool) -> CheckResult:
    path = app.local_dir
    if not path.is_dir():
        return CheckResult(
            app=app, state="missing", message="directory does not exist"
        )

    probe = _git(path, "rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0:
        message = _first_line(probe.stderr).removeprefix("fatal: ")
        if "not a git repository" in message:
            message = "not a git repository"
        return CheckResult(
            app=app, state="not-git", message=message or "not a git repository"
        )
    if probe.stdout.strip() != "true":
        return CheckResult(
            app=app,
            state="not-git",
            message="not a git working tree (bare repository?)",
        )

    fetch_error: str | None = None
    if fetch:
        remotes = _git(path, "remote")
        if remotes.returncode == 0 and remotes.stdout.strip():
            fetched = _git(
                path, "fetch", "--quiet", "--all", timeout=FETCH_TIMEOUT
            )
            if fetched.returncode != 0:
                fetch_error = _first_line(fetched.stderr) or "git fetch failed"

    status = _git(path, "status", "--porcelain", "--untracked-files=normal")
    if status.returncode != 0:
        return CheckResult(
            app=app,
            state="error",
            message=_first_line(status.stderr) or "could not read git status",
            fetch_error=fetch_error,
        )
    changes = sum(1 for line in status.stdout.splitlines() if line)

    branch_probe = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = (
        branch_probe.stdout.strip() if branch_probe.returncode == 0 else None
    )

    upstream_probe = _git(
        path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    upstream = (
        upstream_probe.stdout.strip()
        if upstream_probe.returncode == 0
        else None
    )

    ahead = 0
    behind = 0
    if upstream:
        counts = _git(
            path, "rev-list", "--left-right", "--count", f"{upstream}...HEAD"
        )
        if counts.returncode == 0:
            parts = counts.stdout.split()
            if len(parts) >= 2:
                behind, ahead = int(parts[0]), int(parts[1])

    return CheckResult(
        app=app,
        changes=changes,
        ahead=ahead,
        behind=behind,
        branch=branch,
        upstream=upstream,
        fetch_error=fetch_error,
    )


def get_remote_url(path: Path) -> str | None:
    """Return the checkout's git remote URL, preferring ``origin``."""
    remotes = _git(path, "remote")
    if remotes.returncode != 0:
        return None
    names = remotes.stdout.split()
    if not names:
        return None

    name = "origin" if "origin" in names else names[0]
    remote = _git(path, "remote", "get-url", name)
    if remote.returncode != 0:
        return None
    return remote.stdout.strip() or None


def clone_app(remote: str, target: Path) -> None:
    """Clone ``remote`` into ``target``, creating its parent directories."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SuiteError(f"could not create {target.parent}: {exc}") from exc

    try:
        result = subprocess.run(
            ["git", "clone", "--", remote, str(target)],
            check=False,
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise SuiteError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SuiteError("git clone timed out") from exc
    except OSError as exc:
        raise SuiteError(f"could not run git clone: {exc}") from exc

    if result.returncode != 0:
        message = _first_line(result.stderr) or "unknown error"
        raise SuiteError(f"git clone failed: {message}")


def pull_app(app: App) -> None:
    """Fast-forward ``app``'s checkout to its upstream branch."""
    try:
        result = _git(
            app.local_dir,
            "pull",
            "--ff-only",
            "--no-rebase",
            "--quiet",
            timeout=PULL_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise SuiteError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SuiteError("git pull timed out") from exc
    except OSError as exc:
        raise SuiteError(f"could not run git pull: {exc}") from exc

    if result.returncode != 0:
        message = _first_line(result.stderr) or "unknown error"
        raise SuiteError(f"git pull failed: {message}")


def _git(
    path: Path, *args: str, timeout: int = GIT_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""
