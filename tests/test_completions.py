from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from suite import completions
from suite.cli import cli
from suite.completions import (
    completion_path,
    generate_bash,
    has_bash_completion,
    install_bash_completion,
)
from suite.errors import SuiteError


@click.group()
@click.option("--mode", type=click.Choice(["fast", "slow"]))
@click.option("--out", type=click.Path())
@click.option("--dir", type=click.Path(file_okay=False))
@click.option("--tag", multiple=True)
@click.option("--verbose", count=True)
@click.option("--flag", is_flag=True)
@click.option("--point", type=(int, int))
@click.option("--hidden-opt", hidden=True)
@click.option("-n", "--name")
@click.argument("files", nargs=-1, type=click.Path())
def demo(
    mode: str | None,
    out: str | None,
    dir: str | None,
    tag: tuple[str, ...],
    verbose: int,
    flag: bool,
    point: tuple[int, int],
    hidden_opt: bool,
    name: str | None,
    files: tuple[str, ...],
) -> None:
    """Demo command."""


@demo.command()
@click.option("--level", type=click.Choice(["one", "two"]))
@click.argument("target", type=click.Path())
def run(level: str | None, target: str) -> None:
    """Run something."""


@demo.command(hidden=True)
def secret() -> None:
    """Hidden command."""


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "demo.bash"
    path.write_text(generate_bash(demo, "demo", "1.2.3"), encoding="utf-8")
    return path


def _complete(path: Path, words: list[str]) -> list[str]:
    quoted = " ".join(shlex.quote(word) for word in words)
    command = f"""\
source {shlex.quote(str(path))}
COMP_WORDS=({quoted})
COMP_CWORD={len(words) - 1}
COMPREPLY=()
_demo_complete
printf '%s\\n' "${{COMPREPLY[@]}}"
"""
    result = subprocess.run(
        ["bash", "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_completion_path_uses_bash_completion_user_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv(
        "BASH_COMPLETION_USER_DIR", f"{first}{os.pathsep}{second}"
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert completion_path("suite") == (
        first / "bash-completion" / "completions" / "suite.bash"
    )


def test_completion_path_skips_empty_user_dir_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(
        "BASH_COMPLETION_USER_DIR",
        f"{os.pathsep}{tmp_path / 'chosen'}{os.pathsep}",
    )

    assert completion_path("suite") == (
        tmp_path / "chosen" / "bash-completion" / "completions" / "suite.bash"
    )


def test_completion_path_uses_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BASH_COMPLETION_USER_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert completion_path("suite") == (
        tmp_path / "bash-completion" / "completions" / "suite.bash"
    )


def test_completion_path_falls_back_to_local_share(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BASH_COMPLETION_USER_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert completion_path("suite") == (
        tmp_path
        / ".local"
        / "share"
        / "bash-completion"
        / "completions"
        / "suite.bash"
    )


def test_install_creates_directories_and_overwrites(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.delenv("BASH_COMPLETION_USER_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    path = completion_path("demo")
    path.parent.mkdir(parents=True)
    path.write_text("old\n", encoding="utf-8")

    installed = install_bash_completion(demo, "demo", "1.2.3")

    assert installed == path
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o644
    assert "old" not in path.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert captured.out.strip() == str(path.expanduser().absolute())
    assert "source" in captured.err
    assert captured.err.count("\n") >= 2


def test_install_reports_write_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.delenv("BASH_COMPLETION_USER_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    data_home.mkdir()
    (data_home / "bash-completion").write_text("file", encoding="utf-8")

    with pytest.raises(SuiteError, match="could not write"):
        install_bash_completion(demo, "demo", "1.2.3")


def test_generated_script_passes_bash_syntax_check(
    tmp_path: Path,
) -> None:
    path = _script(tmp_path)

    result = subprocess.run(
        ["bash", "-n", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_script_has_a_header_and_registers_completion(
    tmp_path: Path,
) -> None:
    script = _script(tmp_path).read_text(encoding="utf-8")

    assert "# bash completion for demo 1.2.3" in script
    assert "do not edit" in script
    assert (
        "complete -o nosort -o bashdefault -o default "
        "-F _demo_complete demo" in script
    )


def test_subcommand_completion(tmp_path: Path) -> None:
    path = _script(tmp_path)

    assert "run" in _complete(path, ["demo", ""])
    assert _complete(path, ["demo", "r"]) == ["run"]


def test_hidden_commands_and_options_are_not_suggested(
    tmp_path: Path,
) -> None:
    path = _script(tmp_path)

    suggestions = _complete(path, ["demo", ""])

    assert "secret" not in suggestions
    assert "--hidden-opt" not in suggestions


def test_option_and_short_option_completion(
    tmp_path: Path,
) -> None:
    path = _script(tmp_path)

    suggestions = _complete(path, ["demo", "--"])

    assert "--mode" in suggestions
    assert "--help" in suggestions
    assert "--hidden-opt" not in suggestions

    suggestions = _complete(path, ["demo", "-"])
    assert "-n" in suggestions


def test_choice_completion(tmp_path: Path) -> None:
    path = _script(tmp_path)

    assert _complete(path, ["demo", "--mode", ""]) == [
        "fast",
        "slow",
    ]
    assert _complete(path, ["demo", "run", "--level", ""]) == [
        "one",
        "two",
    ]


def test_equals_completion_for_choice(tmp_path: Path) -> None:
    path = _script(tmp_path)

    assert _complete(path, ["demo", "--mode=f"]) == ["--mode=fast"]


def test_path_and_directory_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    path = _script(tmp_path)

    assert "file.txt" in _complete(path, ["demo", "run", "fi"])
    assert "folder" in _complete(path, ["demo", "--dir", "fo"])
    assert "file.txt" not in _complete(path, ["demo", "--dir", ""])


def test_equals_completion_for_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    path = _script(tmp_path)

    suggestions = _complete(path, ["demo", "--out=fi"])

    assert "--out=file.txt" in suggestions


def test_no_option_completion_after_double_dash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _script(tmp_path)

    suggestions = _complete(path, ["demo", "--", ""])

    assert not any(item.startswith("-") for item in suggestions)


def test_nargs_and_repeated_options_do_not_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _script(tmp_path)

    _complete(path, ["demo", "--tag", "one", "--verbose", "--flag", ""])


def test_tuple_option_completion_does_not_crash(
    tmp_path: Path,
) -> None:
    path = _script(tmp_path)

    _complete(path, ["demo", "--point", "1", ""])


def test_old_bash_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(completions.shutil, "which", lambda _name: "/bin/bash")
    monkeypatch.setattr(
        completions.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="3.2"),
    )

    install_bash_completion(demo, "demo", "1.2.3")

    assert "older than 4.4" in capsys.readouterr().err


def test_missing_bash_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(completions.shutil, "which", lambda _name: None)

    install_bash_completion(demo, "demo", "1.2.3")

    assert "bash was not found" in capsys.readouterr().err


def test_has_bash_completion_detects_installed_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    script = completion_path("cm")
    script.parent.mkdir(parents=True)
    script.write_text("script\n", encoding="utf-8")

    assert has_bash_completion("cm")


def test_has_bash_completion_is_false_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert not has_bash_completion("cm")


def test_cli_completions_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BASH_COMPLETION_USER_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(cli, ["--completions"], prog_name="suite")

    assert result.exit_code == 0
    path = tmp_path / "bash-completion" / "completions" / "suite.bash"
    assert path.is_file()
    assert result.stdout.strip() == str(path)
    assert "source" in result.stderr
    assert "suite" in path.read_text(encoding="utf-8")
