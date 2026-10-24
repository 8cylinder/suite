from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import SuiteError
from .models import App

PROJECTS_FILE = "~/.prompt-projects"

# Dark colors that work well as the prompt's project background.
PROJECT_COLORS = (
    "#1f473d",
    "#394646",
    "#592649",
    "#5c4c3d",
    "#45081a",
    "#995f00",
    "#430f8a",
    "#39471f",
    "#361c17",
    "#0f8a78",
    "#31293d",
    "#21730d",
    "#082c45",
    "#283617",
    "#19661a",
    "#000866",
)


@dataclass(frozen=True, slots=True)
class PromptProject:
    """A project registered in ~/.prompt-projects."""

    name: str
    path: Path
    color: str


def projects_path(path: Path | None = None) -> Path:
    if path is not None:
        return path.expanduser()
    return Path(PROJECTS_FILE).expanduser()


def load_projects(path: Path | None = None) -> dict[str, PromptProject]:
    """Read ~/.prompt-projects as a mapping keyed by project name."""
    file = projects_path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise SuiteError(f"could not read {file}: {exc}") from exc

    projects: dict[str, PromptProject] = {}
    for line in text.splitlines():
        line = line.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        if not name:
            continue
        color = parts[2].strip() if len(parts) > 2 else ""
        projects[name] = PromptProject(name=name, path=Path(parts[1]), color=color)
    return projects


def add_projects(apps: Sequence[App], path: Path | None = None) -> list[App]:
    """Append apps that are not registered yet, returning the added apps."""
    file = projects_path(path)
    projects = load_projects(file)
    missing = [app for app in apps if app.name not in projects]
    if not missing:
        return []

    try:
        existing = file.read_text(encoding="utf-8") if file.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        added = "".join(
            f"{app.name}\t{app.local_dir}\t{_project_color(app.name)}\n" for app in missing
        )
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(existing + added, encoding="utf-8")
    except OSError as exc:
        raise SuiteError(f"could not write {file}: {exc}") from exc
    return missing


def _project_color(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return PROJECT_COLORS[int(digest, 16) % len(PROJECT_COLORS)]
