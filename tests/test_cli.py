from __future__ import annotations

import io
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from rich.console import Console

from suite import cli
from suite.cli import main
from suite.models import App, CheckResult


@pytest.fixture
def config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("SUITE_CONFIG", str(path))
    return path


def test_first_run_creates_config(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["list"])

    assert exit_code == 0
    assert config_file.is_file()
    captured = capsys.readouterr()
    assert "Created config:" in captured.err
    assert "No apps configured." in captured.out
    assert "Config:" in captured.out


def test_add_list_remove(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()
    assert main(["add", "cm", str(local_dir), "--remote", "git@example.com:cm.git"]) == 0

    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert data["apps"] == [
        {
            "name": "cm",
            "local_dir": str(local_dir),
            "remote": "git@example.com:cm.git",
        }
    ]

    assert main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "cm" in listed
    assert str(local_dir) in listed

    assert main(["remove", "cm"]) == 0
    assert "Removed cm" in capsys.readouterr().out
    assert main(["list"]) == 0
    assert "No apps configured." in capsys.readouterr().out


def test_add_duplicate_is_an_error(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "cm").mkdir()
    (tmp_path / "other").mkdir()
    assert main(["add", "cm", str(tmp_path / "cm"), "--remote", "git@example.com:cm.git"]) == 0
    capsys.readouterr()

    assert (
        main(["add", "cm", str(tmp_path / "other"), "--remote", "git@example.com:other.git"]) == 2
    )

    assert "already exists" in capsys.readouterr().err


def test_add_requires_an_existing_directory(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["add", "cm"]) == 2
    assert "path" in capsys.readouterr().err.lower()

    assert main(["add", "cm", str(tmp_path / "missing")]) == 2
    assert "not an existing directory" in capsys.readouterr().err

    assert yaml.safe_load(config_file.read_text(encoding="utf-8"))["apps"] == []


def test_add_detects_the_checkout_remote(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()
    subprocess.run(["git", "-C", str(local_dir), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(local_dir), "remote", "add", "origin", "git@example.com:cm.git"],
        check=True,
        capture_output=True,
    )

    assert main(["add", "cm", str(local_dir)]) == 0

    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert data["apps"][0]["remote"] == "git@example.com:cm.git"


def test_add_without_a_remote_is_an_error(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()

    assert main(["add", "cm", str(local_dir)]) == 2

    assert "no git remote" in capsys.readouterr().err
    assert yaml.safe_load(config_file.read_text(encoding="utf-8"))["apps"] == []


def test_add_rejects_a_file_path(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "cm"
    path.write_text("", encoding="utf-8")

    assert main(["add", "cm", str(path)]) == 2
    assert "not an existing directory" in capsys.readouterr().err


def test_check_reports_missing_app(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "missing"
    local_dir.mkdir()
    assert (
        main(["add", "missing-app", str(local_dir), "--remote", "git@example.com:missing.git"]) == 0
    )
    local_dir.rmdir()
    capsys.readouterr()

    exit_code = main(["check", "--no-fetch"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "missing-app" in captured.out
    assert "missing:" in captured.out
    assert "1 with problems" in captured.out


def test_check_prints_each_app_as_it_is_checked(
    config_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        assert (
            main(
                [
                    "add",
                    name,
                    str(tmp_path / name),
                    "--remote",
                    f"git@example.com:{name}.git",
                ]
            )
            == 0
        )

    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    checked: list[str] = []

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        if checked:
            assert checked[0] in output.getvalue()
        checked.append(app.name)
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)

    assert main(["check", "--no-fetch"]) == 0
    assert checked == ["one", "two"]


def test_check_unknown_app_is_an_error(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "nope"]) == 2
    assert "unknown app" in capsys.readouterr().err


def test_check_shows_prompt_project_status(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    projects_file = home / ".prompt-projects"
    projects_file.write_text("one\t/tmp/one\t#111111\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        assert (
            main(
                [
                    "add",
                    name,
                    str(tmp_path / name),
                    "--remote",
                    f"git@example.com:{name}.git",
                ]
            )
            == 0
        )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert "PRJ" in output
    assert "one  ✓" in output
    assert "two  x" in output
    assert projects_file.read_text(encoding="utf-8") == "one\t/tmp/one\t#111111\n"


def test_check_colors_the_status_columns(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".prompt-projects").write_text("one\t/tmp/one\t#111111\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(
            app=app,
            changes=1,
            behind=2,
            upstream="origin/main",
            branch="main",
        )

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(
        cli, "Console", lambda: Console(force_terminal=True, color_system="standard")
    )
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert "\x1b[32m✓" in output
    assert "\x1b[33m1 change" in output
    assert "\x1b[33m2 commits" in output


def test_check_reports_commits_to_push(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(
            app=app,
            ahead=2,
            upstream="origin/main",
            branch="main",
        )

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert "TO PUSH" in output
    assert "2 commits" in output
    assert "1 with commits to push" in output
    assert "origin/main" in output
    assert "(2 ahead)" not in output


def test_check_update_dot_project_adds_missing_projects(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    projects_file = home / ".prompt-projects"
    projects_file.write_text("one\t/tmp/one\t#111111\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        assert (
            main(
                [
                    "add",
                    name,
                    str(tmp_path / name),
                    "--remote",
                    f"git@example.com:{name}.git",
                ]
            )
            == 0
        )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch", "--update-dot-project"]) == 0

    captured = capsys.readouterr()
    assert "Added 1 project to ~/.prompt-projects" in captured.out
    assert "one  ✓" in captured.out
    assert "two  ✓" in captured.out
    lines = projects_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "one\t/tmp/one\t#111111"
    assert lines[1].startswith(f"two\t{tmp_path / 'two'}\t#")


def test_sync_from_org_file(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    org_file = tmp_path / "apps.org"
    org_file.write_text(
        """\
* Apps
** cm
Generate a commit message.
remote: =git@example.com:cm.git=
""",
        encoding="utf-8",
    )

    assert main(["sync", str(org_file)]) == 0
    assert "1 added" in capsys.readouterr().out
    assert main(["list"]) == 0
    assert "cm" in capsys.readouterr().out

    assert main(["sync", str(org_file)]) == 0
    assert "no changes" in capsys.readouterr().out


def test_config_show(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config"]) == 0
    assert str(config_file) in capsys.readouterr().out

    assert main(["config", "--show"]) == 0
    output = capsys.readouterr().out
    assert "apps_root:" in output
    assert "apps: []" in output


def test_short_help_flag(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-h"]) == 0

    output = capsys.readouterr().out
    assert "Usage: suite" in output
    assert "--completions" in output
    assert not config_file.exists()


def test_subcommand_short_help_flag(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "-h"]) == 0

    output = capsys.readouterr().out
    assert "Usage: suite check" in output
    assert not config_file.exists()


def test_version_matches_pyproject(capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    expected = f"suite {pyproject['project']['version']}"

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == expected


def test_completions_installs_a_script(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    assert main(["--completions"]) == 0

    script_path = data_home / "bash-completion" / "completions" / "suite"
    assert script_path.is_file()
    script = script_path.read_text(encoding="utf-8")
    assert "_SUITE_COMPLETE=bash_complete" in script
    assert "complete -o nosort -F _suite_completion suite" in script

    output = capsys.readouterr().out
    assert f"Completion script: {script_path}" in output
    assert f"Source it now: source {script_path}" in output
    assert not config_file.exists()


def test_completions_reports_write_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv("XDG_DATA_HOME", str(blocker))

    assert main(["--completions"]) == 2
    assert "could not write completion script" in capsys.readouterr().err


def test_bash_completion_protocol(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("_SUITE_COMPLETE", "bash_complete")
    monkeypatch.setenv("COMP_WORDS", "suite ch")
    monkeypatch.setenv("COMP_CWORD", "1")

    assert main([]) == 0
    assert "plain,check" in capsys.readouterr().out


def test_completions_overwrites_an_existing_script(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    script_path = data_home / "bash-completion" / "completions" / "suite"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("old script\n", encoding="utf-8")

    assert main(["--completions"]) == 0

    script = script_path.read_text(encoding="utf-8")
    assert "old script" not in script
    assert "complete -o nosort" in script


def test_keyboard_interrupt_is_a_clean_exit(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0
    capsys.readouterr()

    def interrupted(app: App, *, fetch: bool = True) -> CheckResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "check_app", interrupted)

    assert main(["check", "--no-fetch"]) == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Traceback" not in captured.out
