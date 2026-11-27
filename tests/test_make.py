from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from suite import make
from suite.errors import SuiteError
from suite.make import has_install, run_install


def _write_makefile(path: Path, contents: str) -> None:
    (path / "Makefile").write_text(contents, encoding="utf-8")


def test_has_install_detects_the_target(tmp_path: Path) -> None:
    _write_makefile(tmp_path, "install:\n\t@true\n")

    assert has_install(tmp_path)


def test_has_install_is_false_without_the_target(tmp_path: Path) -> None:
    _write_makefile(tmp_path, "all:\n\t@true\n")

    assert not has_install(tmp_path)


def test_has_install_is_false_without_a_makefile(tmp_path: Path) -> None:
    assert not has_install(tmp_path)


def test_has_install_is_false_without_make(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_makefile(tmp_path, "install:\n\t@true\n")
    monkeypatch.setattr(make.shutil, "which", lambda _name: None)

    assert not has_install(tmp_path)


def test_has_install_is_false_when_make_cannot_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_makefile(tmp_path, "install:\n\t@true\n")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(make.subprocess, "run", fail)

    assert not has_install(tmp_path)


def test_run_install_runs_the_target(tmp_path: Path) -> None:
    _write_makefile(tmp_path, "install:\n\t@touch installed\n")

    run_install(tmp_path)

    assert (tmp_path / "installed").is_file()


def test_run_install_reports_a_failure(tmp_path: Path) -> None:
    _write_makefile(tmp_path, "install:\n\t@exit 1\n")

    with pytest.raises(SuiteError, match="make install failed"):
        run_install(tmp_path)


def test_run_install_requires_make(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(make.subprocess, "run", missing)

    with pytest.raises(SuiteError, match="make is not installed"):
        run_install(tmp_path)


def test_run_install_reports_a_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def timed_out(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("make", 1)

    monkeypatch.setattr(make.subprocess, "run", timed_out)

    with pytest.raises(SuiteError, match="make install timed out"):
        run_install(tmp_path)


def test_run_install_reports_an_os_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(make.subprocess, "run", fail)

    with pytest.raises(SuiteError, match="could not run make install"):
        run_install(tmp_path)
