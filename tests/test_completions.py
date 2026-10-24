from __future__ import annotations

from pathlib import Path

import pytest

from suite.completions import completion_path, has_bash_completion, install_bash_completion


def test_completion_path_uses_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert completion_path("suite") == tmp_path / "bash-completion" / "completions" / "suite"


def test_completion_path_falls_back_to_local_share(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    expected = tmp_path / ".local" / "share" / "bash-completion" / "completions" / "suite"
    assert completion_path("suite") == expected


def test_install_writes_the_completion_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    path = install_bash_completion()

    assert path.is_file()
    script = path.read_text(encoding="utf-8")
    assert "_SUITE_COMPLETE=bash_complete" in script
    assert "complete -o nosort -F _suite_completion suite" in script


def test_has_bash_completion_detects_an_installed_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = completion_path("cm")
    path.parent.mkdir(parents=True)
    path.write_text("script\n", encoding="utf-8")

    assert has_bash_completion("cm")


def test_has_bash_completion_is_false_when_the_script_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert not has_bash_completion("cm")


def test_has_bash_completion_uses_the_local_share_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    path = completion_path("cm")
    path.parent.mkdir(parents=True)
    path.write_text("script\n", encoding="utf-8")

    assert has_bash_completion("cm")
