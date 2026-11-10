from __future__ import annotations

import io
import re
import subprocess
import sys
import threading
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


@pytest.fixture
def tty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Present stdout as a terminal so table chrome is printed."""
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)


def _table_fields(output: str, name: str) -> list[str]:
    """Split a rendered table row into its cells, keeping spaces inside cells."""
    for line in output.splitlines():
        cells = re.split(r"\s{2,}", line.strip())
        if cells and cells[0] == name:
            return cells
    raise AssertionError(f"no table row for {name!r} in:\n{output}")


def test_first_run_creates_config(
    config_file: Path, tty_output: None, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["list"])

    assert exit_code == 0
    assert config_file.is_file()
    captured = capsys.readouterr()
    assert "Created config:" in captured.err
    assert "No apps configured." in captured.out
    assert "Config:" in captured.out


def test_plain_invocation_lists_apps(
    config_file: Path, tty_output: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()
    assert main(["add", "cm", str(local_dir), "--remote", "git@example.com:cm.git"]) == 0
    capsys.readouterr()

    assert main([]) == 0

    output = capsys.readouterr().out
    assert "NAME" in output
    assert "cm" in output
    assert str(local_dir) in output
    assert "Usage: suite" not in output


def test_list_prints_rows_only_when_piped(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("zeta", "alpha"):
        (tmp_path / name).mkdir()
        assert (
            main(["add", name, str(tmp_path / name), "--remote", f"git@example.com:{name}.git"])
            == 0
        )
    capsys.readouterr()
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)

    assert main(["list"]) == 0

    output = capsys.readouterr().out
    lines = output.splitlines()
    assert lines == [
        f"alpha\t{tmp_path / 'alpha'}\tgit@example.com:alpha.git",
        f"zeta\t{tmp_path / 'zeta'}\tgit@example.com:zeta.git",
    ]
    assert "NAME" not in output
    assert "Config:" not in output


def test_list_no_apps_message_goes_to_stderr_when_piped(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)

    assert main(["list"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "No apps configured." in captured.err


def test_add_list_remove(
    config_file: Path, tty_output: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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


def test_add_stores_home_paths_with_tilde(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    in_home = home / "dev" / "cm"
    outside = tmp_path / "opt" / "cm"
    in_home.mkdir(parents=True)
    outside.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    assert main(["add", "home-app", str(in_home), "--remote", "git@example.com:home.git"]) == 0
    assert main(["add", "outside-app", str(outside), "--remote", "git@example.com:out.git"]) == 0

    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    stored = {app["name"]: app["local_dir"] for app in data["apps"]}
    assert stored["home-app"] == "~/dev/cm"
    assert stored["outside-app"] == str(outside)
    assert "Added home-app -> ~/dev/cm" in capsys.readouterr().out


def test_list_expands_home_paths_to_absolute(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    config_file.write_text(
        """\
apps:
  - name: cm
    local_dir: ~/dev/cm
    remote: git@example.com:cm.git
  - name: other
    local_dir: $HOME/dev/other
    remote: git@example.com:other.git
""",
        encoding="utf-8",
    )

    assert main(["list"]) == 0

    output = capsys.readouterr().out
    assert f"cm\t{home / 'dev' / 'cm'}\tgit@example.com:cm.git" in output
    assert f"other\t{home / 'dev' / 'other'}\tgit@example.com:other.git" in output
    assert "~/" not in output


def test_add_misc_writes_kind(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "bin"
    local_dir.mkdir()

    assert (
        main(
            [
                "add",
                "bin",
                str(local_dir),
                "--remote",
                "git@example.com:bin.git",
                "--misc",
            ]
        )
        == 0
    )

    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert data["apps"] == [
        {
            "name": "bin",
            "local_dir": str(local_dir),
            "remote": "git@example.com:bin.git",
            "kind": "misc",
        }
    ]


def test_add_existing_app_can_be_overwritten(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "cm").mkdir()
    (tmp_path / "other").mkdir()
    assert main(["add", "cm", str(tmp_path / "cm"), "--remote", "git@example.com:cm.git"]) == 0

    prompts: list[tuple[str, bool]] = []

    def fake_confirm(message: str, *, default: bool = False) -> bool:
        prompts.append((message, default))
        return True

    monkeypatch.setattr(cli.click, "confirm", fake_confirm)
    capsys.readouterr()

    assert (
        main(
            [
                "add",
                "cm",
                str(tmp_path / "other"),
                "--remote",
                "git@example.com:other.git",
                "--misc",
            ]
        )
        == 0
    )

    assert prompts == [("App 'cm' already exists. Overwrite?", False)]
    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert data["apps"] == [
        {
            "name": "cm",
            "local_dir": str(tmp_path / "other"),
            "remote": "git@example.com:other.git",
            "kind": "misc",
        }
    ]
    assert "Updated cm" in capsys.readouterr().out


def test_add_existing_app_can_keep_the_record(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "cm").mkdir()
    (tmp_path / "other").mkdir()
    assert main(["add", "cm", str(tmp_path / "cm"), "--remote", "git@example.com:cm.git"]) == 0
    before = config_file.read_text(encoding="utf-8")

    monkeypatch.setattr(cli.click, "confirm", lambda message, *, default=False: False)
    capsys.readouterr()

    assert (
        main(["add", "cm", str(tmp_path / "other"), "--remote", "git@example.com:other.git"]) == 0
    )

    assert config_file.read_text(encoding="utf-8") == before
    assert "Kept existing cm." in capsys.readouterr().out


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
    config_file: Path, tty_output: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
    assert "with problems" not in captured.out


def test_list_sorts_apps_by_name(
    config_file: Path, tty_output: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("zeta", "alpha", "mu"):
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
    capsys.readouterr()

    assert main(["list"]) == 0

    lines = capsys.readouterr().out.splitlines()
    names = [line.split()[0] for line in lines[1:] if line and not line.startswith("Config:")]
    assert names == ["alpha", "mu", "zeta"]


def test_check_sorts_apps_by_name(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("zeta", "alpha", "mu"):
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
    capsys.readouterr()

    checked: list[str] = []

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        checked.append(app.name)
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)

    assert main(["check", "--no-fetch"]) == 0
    assert sorted(checked) == ["alpha", "mu", "zeta"]
    names = [line.split("\t")[0] for line in capsys.readouterr().out.splitlines()]
    assert names == ["alpha", "mu", "zeta"]


def test_check_runs_apps_concurrently(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
    capsys.readouterr()

    barrier = threading.Barrier(2, timeout=5)

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        # Both workers must be in flight at the same time for this to return.
        barrier.wait()
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)

    assert main(["check", "--no-fetch"]) == 0
    assert not barrier.broken


def test_check_prints_results_after_all_checks_finish(
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
        assert output.getvalue() == ""
        checked.append(app.name)
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)

    assert main(["check", "--no-fetch"]) == 0
    assert sorted(checked) == ["one", "two"]
    lines = output.getvalue().splitlines()
    assert [line.split("\t")[0] for line in lines] == ["one", "two"]


def test_check_prints_rows_only_when_piped(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "one\tx\tx\tclean\t-\tno upstream\tdetached HEAD",
    ]
    assert captured.err == ""


def test_check_piped_row_keeps_detail_in_last_field(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_dir = tmp_path / "missing"
    local_dir.mkdir()
    assert (
        main(["add", "missing-app", str(local_dir), "--remote", "git@example.com:missing.git"]) == 0
    )
    local_dir.rmdir()
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 1

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    fields = lines[0].split("\t")
    assert len(fields) == 7
    assert fields[0] == "missing-app"
    assert fields[6] == f"missing: {local_dir}"


def test_check_unknown_app_is_an_error(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "nope"]) == 2
    assert "unknown app" in capsys.readouterr().err


def test_check_reports_fetch_warnings_on_stderr(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app, fetch_error="could not resolve host")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check"]) == 0

    captured = capsys.readouterr()
    assert "suite: warning: one: could not resolve host" in captured.err
    assert "could not resolve host" not in captured.out


def test_check_shows_prompt_project_status(
    config_file: Path,
    tty_output: None,
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
    assert _table_fields(output, "one")[1] == "✓"
    assert _table_fields(output, "two")[1] == "x"
    assert projects_file.read_text(encoding="utf-8") == "one\t/tmp/one\t#111111\n"


def test_check_separates_header_from_rows(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    lines = capsys.readouterr().out.splitlines()
    header = next(index for index, line in enumerate(lines) if "APP" in line)
    separator = lines[header + 1].strip()
    assert separator
    assert set(separator) == {"─"}
    assert "one" in lines[header + 2]


def test_check_shows_completion_status(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    script = data_home / "bash-completion" / "completions" / "one"
    script.parent.mkdir(parents=True)
    script.write_text("script\n", encoding="utf-8")

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
    assert "CMP" in output
    assert _table_fields(output, "one")[2] == "✓"
    assert _table_fields(output, "two")[2] == "x"


def test_check_shows_dash_for_misc_completion(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    for name in ("bin", "one"):
        script = data_home / "bash-completion" / "completions" / name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("script\n", encoding="utf-8")

        (tmp_path / name).mkdir()
        args = ["add", name, str(tmp_path / name), "--remote", f"git@example.com:{name}.git"]
        if name == "bin":
            args.append("--misc")
        assert main(args) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert _table_fields(output, "bin")[2] == "-"
    assert _table_fields(output, "one")[2] == "✓"


def test_check_colors_the_status_columns(
    config_file: Path,
    tty_output: None,
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
    tty_output: None,
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
    assert "with commits to push" not in output
    assert "DETAIL" not in output
    assert "origin/main" not in output
    assert "(2 ahead)" not in output


def test_check_shows_detail_column_when_any_row_needs_it(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("gone", "tracked"):
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
    (tmp_path / "gone").rmdir()

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        if app.name == "tracked":
            return CheckResult(app=app, upstream="origin/main", branch="main")
        return CheckResult(app=app, state="missing")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 1

    output = capsys.readouterr().out
    assert "DETAIL" in output
    tracked = _table_fields(output, "tracked")
    assert tracked == ["tracked", "x", "x", "clean", "up to date", "up to date"]
    assert _table_fields(output, "gone")[6].startswith("missing: ")


def test_check_shows_branch_when_there_is_no_upstream(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app, branch="main")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert _table_fields(output, "one")[6] == "main"


def test_check_piped_output_omits_blank_detail_column(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert main(["add", "one", str(tmp_path / "one"), "--remote", "git@example.com:one.git"]) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app, upstream="origin/main", branch="main")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "one\tx\tx\tclean\tup to date\tup to date",
    ]


def test_check_update_dot_project_adds_missing_projects(
    config_file: Path,
    tty_output: None,
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
    assert _table_fields(captured.out, "one")[1] == "✓"
    assert _table_fields(captured.out, "two")[1] == "✓"
    lines = projects_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "one\t/tmp/one\t#111111"
    assert lines[1].startswith(f"two\t{tmp_path / 'two'}\t#")


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
