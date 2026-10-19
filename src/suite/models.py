from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CheckState = Literal["ok", "missing", "not-git", "error"]


@dataclass(frozen=True, slots=True)
class App:
    """An application tracked by suite."""

    name: str
    local_dir: Path
    remote: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SuiteEntry:
    """An application read from suite.org."""

    name: str
    description: str | None = None
    remote: str | None = None
    local_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The result of checking one application's repository."""

    app: App
    state: CheckState = "ok"
    changes: int = 0
    ahead: int = 0
    behind: int = 0
    branch: str | None = None
    upstream: str | None = None
    message: str | None = None
    fetch_error: str | None = None

    @property
    def has_problem(self) -> bool:
        return self.state != "ok"
