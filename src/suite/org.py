from __future__ import annotations

import re
from pathlib import Path

from .models import SuiteEntry

_APP_HEADING = re.compile(r"^\*\*[ \t]+(.+?)[ \t]*$")
_BOLD_REMOTE = re.compile(r"^remote:[ \t]*=(.*?)=[ \t]*$")
_KEY_VALUE = re.compile(r"^(remote|local|local_dir|dir|path):[ \t]*(.*?)[ \t]*$", re.IGNORECASE)


def parse_org(text: str) -> list[SuiteEntry]:
    """Parse applications from an org-mode document.

    A level-two heading (``** name``) starts an application. Any following
    non-keyword text is used as its description. The ``remote:``, ``local:``,
    ``dir:``, and ``path:`` keywords are recognized.
    """
    entries: list[SuiteEntry] = []
    name: str | None = None
    description: list[str] = []
    remote: str | None = None
    local_dir: Path | None = None

    def flush() -> None:
        nonlocal name, description, remote, local_dir
        if name is not None:
            entries.append(
                SuiteEntry(
                    name=name,
                    description=" ".join(description) or None,
                    remote=remote,
                    local_dir=local_dir,
                )
            )
        name = None
        description = []
        remote = None
        local_dir = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = _APP_HEADING.match(line)
        if heading:
            flush()
            name = heading.group(1).strip()
            continue
        if name is None or not line:
            continue

        bold_remote = _BOLD_REMOTE.match(line)
        if bold_remote:
            remote = bold_remote.group(1).strip() or None
            continue

        key_value = _KEY_VALUE.match(line)
        if key_value:
            key = key_value.group(1).lower()
            value = _unwrap_org_value(key_value.group(2))
            if key == "remote":
                remote = value or None
            else:
                local_dir = Path(value).expanduser() if value else None
            continue

        description.append(line)

    flush()
    return entries


def _unwrap_org_value(value: str) -> str:
    """Strip org emphasis markers around a value, e.g. ``=path/to/app=``."""
    value = value.strip()
    if len(value) >= 2 and value.startswith("=") and value.endswith("="):
        return value[1:-1].strip()
    return value
