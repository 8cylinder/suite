from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import SuiteError

MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
MAKE_TIMEOUT = 600


def has_install(path: Path) -> bool:
    """Return True when ``path`` has a make install target."""
    if shutil.which("make") is None:
        return False
    if not any((path / name).is_file() for name in MAKEFILES):
        return False
    try:
        result = subprocess.run(
            ["make", "-C", str(path), "-n", "install"],
            check=False,
            capture_output=True,
            text=True,
            timeout=MAKE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def run_install(path: Path) -> None:
    """Run ``make install`` in ``path``."""
    try:
        result = subprocess.run(
            ["make", "-C", str(path), "install"],
            check=False,
            capture_output=True,
            text=True,
            timeout=MAKE_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise SuiteError("make is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SuiteError("make install timed out") from exc
    except OSError as exc:
        raise SuiteError(f"could not run make install: {exc}") from exc

    if result.returncode != 0:
        message = _first_line(result.stderr) or _first_line(result.stdout)
        raise SuiteError(f"make install failed: {message or 'unknown error'}")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""
