from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / ".githooks" / "pre-commit"


def _run_hook(
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
    *,
    record: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    monkeypatch.setenv("PATH", f"{path}:/usr/bin:/bin")
    if record is not None:
        monkeypatch.setenv("GITLEAKS_RECORD", str(record))
    return subprocess.run(
        ["/bin/bash", str(HOOK)],
        check=False,
        capture_output=True,
        text=True,
    )


def _stub(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "gitleaks"
    stub.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    stub.chmod(0o755)
    return tmp_path


def test_hook_parses() -> None:
    result = subprocess.run(
        ["/bin/bash", "-n", str(HOOK)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_missing_gitleaks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _run_hook(monkeypatch, tmp_path)

    assert result.returncode == 1
    assert "gitleaks" in result.stderr
    assert "gitleaks#installing" in result.stderr


def test_old_gitleaks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = _stub(
        tmp_path,
        'if [ "$1" = version ]; then echo 8.16.0; exit 0; fi\nexit 0\n',
    )

    result = _run_hook(monkeypatch, path)

    assert result.returncode == 1
    assert "8.19" in result.stderr


def test_current_gitleaks_records_the_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = tmp_path / "record"
    path = _stub(
        tmp_path,
        'if [ "$1" = version ]; then echo 8.30.1; exit 0; fi\n'
        'printf "%s\\n" "$*" > "$GITLEAKS_RECORD"\n'
        "exit 0\n",
    )

    result = _run_hook(monkeypatch, path, record=record)

    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8").strip() == (
        "git --staged --redact --no-banner --verbose"
    )


def test_gitleaks_failure_is_propagated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _stub(
        tmp_path,
        'if [ "$1" = version ]; then echo 8.30.1; exit 0; fi\nexit 1\n',
    )

    result = _run_hook(monkeypatch, path)

    assert result.returncode == 1


def test_hook_is_executable() -> None:
    assert os.access(HOOK, os.X_OK)
