from __future__ import annotations

import io
import re
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from typing import Any

import pytest

from suite import cli
from suite.cli import main
from suite.errors import SuiteError
from suite.models import App, CheckResult


@pytest.fixture
def config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    path = config_home / "suite" / "config.toml"
    path.parent.mkdir(parents=True)
    return path


def _read_config(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def tty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Present stdout as a terminal so table chrome is printed."""
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)


def _table_fields(output: str, name: str) -> list[str]:
    """Split a table row into cells, keeping spaces inside cells."""
    for line in output.splitlines():
        cells = re.split(r"\s{2,}", line.strip())
        if cells and cells[0] == name:
            return [str(cell) for cell in cells]
    raise AssertionError(f"no table row for {name!r} in:\n{output}")


def test_first_run_creates_config(
    config_file: Path, tty_output: None, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([])

    assert exit_code == 0
    assert config_file.is_file()
    captured = capsys.readouterr()
    assert "Created config:" in captured.err
    assert "No apps configured." in captured.out
    assert "Config:" not in captured.out


def test_plain_invocation_runs_check(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()
    assert (
        main(
            ["add", "cm", str(local_dir), "--remote", "git@example.com:cm.git"]
        )
        == 0
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main([]) == 0

    output = capsys.readouterr().out
    assert "App" in output
    assert "cm" in output
    assert str(local_dir) in output
    assert "Usage: suite" not in output


def test_plain_invocation_checks_when_piped(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("zeta", "alpha"):
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
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main([]) == 0

    output = capsys.readouterr().out
    lines = output.splitlines()
    alpha = f"alpha\t{tmp_path / 'alpha'}\tx\tx\tclean"
    zeta = f"zeta\t{tmp_path / 'zeta'}\tx\tx\tclean"
    assert lines == [
        f"{alpha}\t-\tno upstream\tdetached HEAD",
        f"{zeta}\t-\tno upstream\tdetached HEAD",
    ]
    assert "App" not in output
    assert "Config:" not in output


def test_no_apps_message_goes_to_stderr_when_piped(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)

    assert main([]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "No apps configured." in captured.err


def test_add_remove(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()
    assert (
        main(
            ["add", "cm", str(local_dir), "--remote", "git@example.com:cm.git"]
        )
        == 0
    )

    data = _read_config(config_file)
    assert data["app"] == [
        {
            "name": "cm",
            "local_dir": str(local_dir),
            "remote": "git@example.com:cm.git",
        }
    ]

    assert main(["remove", "cm"]) == 0
    assert "Removed cm" in capsys.readouterr().out
    assert main([]) == 0
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

    assert (
        main(
            [
                "add",
                "home-app",
                str(in_home),
                "--remote",
                "git@example.com:home.git",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "add",
                "outside-app",
                str(outside),
                "--remote",
                "git@example.com:out.git",
            ]
        )
        == 0
    )

    data = _read_config(config_file)
    stored = {app["name"]: app["local_dir"] for app in data["app"]}
    assert stored["home-app"] == "~/dev/cm"
    assert stored["outside-app"] == str(outside)
    assert "Added home-app -> ~/dev/cm" in capsys.readouterr().out


def test_check_expands_home_paths_to_absolute(
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
[[app]]
name = "cm"
local_dir = "~/dev/cm"
remote = "git@example.com:cm.git"

[[app]]
name = "other"
local_dir = "$HOME/dev/other"
remote = "git@example.com:other.git"
""",
        encoding="utf-8",
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert f"cm\t{home / 'dev' / 'cm'}\t" in output
    assert f"other\t{home / 'dev' / 'other'}\t" in output
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

    data = _read_config(config_file)
    assert data["app"] == [
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
    assert (
        main(
            [
                "add",
                "cm",
                str(tmp_path / "cm"),
                "--remote",
                "git@example.com:cm.git",
            ]
        )
        == 0
    )

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
    data = _read_config(config_file)
    assert data["app"] == [
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
    assert (
        main(
            [
                "add",
                "cm",
                str(tmp_path / "cm"),
                "--remote",
                "git@example.com:cm.git",
            ]
        )
        == 0
    )
    before = config_file.read_text(encoding="utf-8")

    monkeypatch.setattr(
        cli.click, "confirm", lambda message, *, default=False: False
    )
    capsys.readouterr()

    assert (
        main(
            [
                "add",
                "cm",
                str(tmp_path / "other"),
                "--remote",
                "git@example.com:other.git",
            ]
        )
        == 0
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

    assert _read_config(config_file).get("app", []) == []


def test_add_detects_the_checkout_remote(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()
    subprocess.run(
        ["git", "-C", str(local_dir), "init"], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(local_dir),
            "remote",
            "add",
            "origin",
            "git@example.com:cm.git",
        ],
        check=True,
        capture_output=True,
    )

    assert main(["add", "cm", str(local_dir)]) == 0

    data = _read_config(config_file)
    assert data["app"][0]["remote"] == "git@example.com:cm.git"


def test_add_without_a_remote_is_an_error(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "cm"
    local_dir.mkdir()

    assert main(["add", "cm", str(local_dir)]) == 2

    assert "no git remote" in capsys.readouterr().err
    assert _read_config(config_file).get("app", []) == []


def test_add_rejects_a_file_path(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "cm"
    path.write_text("", encoding="utf-8")

    assert main(["add", "cm", str(path)]) == 2
    assert "not an existing directory" in capsys.readouterr().err


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Suite Test",
            "-c",
            "user.email=suite@example.com",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
        check=True,
    )


def test_install_clones_a_configured_app(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    apps_root = tmp_path / "apps"
    target = apps_root / "cm"
    origin = tmp_path / "repos" / "cm"
    _make_repo(origin)
    config_file.write_text(
        f"""\
apps_root = "{apps_root}"

[[app]]
name = "cm"
local_dir = "{target}"
remote = "{origin}"
""",
        encoding="utf-8",
    )

    assert main(["install", "cm"]) == 0

    assert (target / "README.md").is_file()
    assert (target / ".git").is_dir()
    data = _read_config(config_file)
    assert data["app"] == [
        {
            "name": "cm",
            "local_dir": str(target),
            "remote": str(origin),
        }
    ]
    assert "Installed cm ->" in capsys.readouterr().out


def test_install_rejects_an_unknown_app(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text(
        f'apps_root = "{tmp_path / "apps"}"\n', encoding="utf-8"
    )

    assert main(["install", "cm"]) == 2

    assert "app 'cm' is not configured" in capsys.readouterr().err


def test_install_warns_when_the_path_already_exists(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "apps" / "cm"
    target.mkdir(parents=True)
    config_file.write_text(
        f"""\
apps_root = "{tmp_path / "apps"}"

[[app]]
name = "cm"
local_dir = "{target}"
remote = "git@example.com:cm.git"
""",
        encoding="utf-8",
    )

    assert main(["install", "cm"]) == 0

    captured = capsys.readouterr()
    assert "warning" in captured.err
    assert "cm already exists" in captured.err
    assert "Installed" not in captured.out


def test_install_rejects_an_empty_app(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["install", "  "]) == 2

    assert "cannot be empty" in capsys.readouterr().err


def test_install_requires_a_configured_remote(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file.write_text(
        f"""\
apps_root = "{tmp_path / "apps"}"

[[app]]
name = "cm"
local_dir = "{tmp_path / "apps" / "cm"}"
""",
        encoding="utf-8",
    )

    assert main(["install", "cm"]) == 2

    assert "no git remote" in capsys.readouterr().err


def test_install_reports_a_clone_failure(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "apps" / "cm"
    config_file.write_text(
        f"""\
apps_root = "{tmp_path / "apps"}"

[[app]]
name = "cm"
local_dir = "{target}"
remote = "{tmp_path / "missing"}"
""",
        encoding="utf-8",
    )

    assert main(["install", "cm"]) == 2

    assert "git clone failed" in capsys.readouterr().err
    assert not target.exists()


def test_check_reports_missing_app(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_dir = tmp_path / "missing"
    local_dir.mkdir()
    assert (
        main(
            [
                "add",
                "missing-app",
                str(local_dir),
                "--remote",
                "git@example.com:missing.git",
            ]
        )
        == 0
    )
    local_dir.rmdir()
    capsys.readouterr()

    exit_code = main(["check", "--no-fetch"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "missing-app" in captured.out
    assert "missing:" in captured.out
    assert "with problems" not in captured.out


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
    names = [
        line.split("\t")[0] for line in capsys.readouterr().out.splitlines()
    ]
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
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        f"one\t{tmp_path / 'one'}\tx\tx\tclean\t-\tno upstream\tdetached HEAD",
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
        main(
            [
                "add",
                "missing-app",
                str(local_dir),
                "--remote",
                "git@example.com:missing.git",
            ]
        )
        == 0
    )
    local_dir.rmdir()
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 1

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    fields = lines[0].split("\t")
    assert len(fields) == 8
    assert fields[0] == "missing-app"
    assert fields[7] == f"missing: {local_dir}"


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
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app, fetch_error="could not resolve host")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check"]) == 0

    captured = capsys.readouterr()
    assert "warning: one: could not resolve host" in captured.err
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
    assert _table_fields(output, "one")[2] == "✓"
    assert _table_fields(output, "two")[2] == "x"
    assert (
        projects_file.read_text(encoding="utf-8") == "one\t/tmp/one\t#111111\n"
    )


def test_check_separates_header_from_rows(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    lines = capsys.readouterr().out.splitlines()
    header = next(index for index, line in enumerate(lines) if "App" in line)
    separator = lines[header + 1].strip()
    assert separator
    assert set(separator) == {"─"}
    assert "one" in lines[header + 2]


def test_check_groups_misc_apps_first_with_separator(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("two", "bin", "one", "extra"):
        (tmp_path / name).mkdir()
        args = [
            "add",
            name,
            str(tmp_path / name),
            "--remote",
            f"git@example.com:{name}.git",
        ]
        if name in ("bin", "extra"):
            args.append("--misc")
        assert main(args) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    lines = capsys.readouterr().out.splitlines()

    def row_index(name: str) -> int:
        return next(
            index for index, line in enumerate(lines) if line.startswith(name)
        )

    assert row_index("bin") < row_index("extra")
    assert row_index("extra") < row_index("one") < row_index("two")
    separator = lines[row_index("extra") + 1].strip()
    assert separator
    assert set(separator) == {"─"}


def test_check_piped_output_groups_misc_apps_first(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("two", "bin", "one"):
        (tmp_path / name).mkdir()
        args = [
            "add",
            name,
            str(tmp_path / name),
            "--remote",
            f"git@example.com:{name}.git",
        ]
        if name == "bin":
            args.append("--misc")
        assert main(args) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    names = [
        line.split("\t")[0] for line in capsys.readouterr().out.splitlines()
    ]
    assert names == ["bin", "one", "two"]


def test_check_section_rule_has_a_distinct_color(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("bin", "one"):
        (tmp_path / name).mkdir()
        args = [
            "add",
            name,
            str(tmp_path / name),
            "--remote",
            f"git@example.com:{name}.git",
        ]
        if name == "bin":
            args.append("--misc")
        assert main(args) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["--color", "always", "check", "--no-fetch"]) == 0

    rules = [
        line for line in capsys.readouterr().out.splitlines() if "─" in line
    ]
    assert len(rules) == 2
    assert rules[0] != rules[1]


def test_check_shows_completion_status(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    script = data_home / "bash-completion" / "completions" / "one.bash"
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
    assert _table_fields(output, "one")[3] == "✓"
    assert _table_fields(output, "two")[3] == "x"


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
        script = data_home / "bash-completion" / "completions" / f"{name}.bash"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("script\n", encoding="utf-8")

        (tmp_path / name).mkdir()
        args = [
            "add",
            name,
            str(tmp_path / name),
            "--remote",
            f"git@example.com:{name}.git",
        ]
        if name == "bin":
            args.append("--misc")
        assert main(args) == 0

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app)

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert _table_fields(output, "bin")[3] == "-"
    assert _table_fields(output, "one")[3] == "✓"


def test_check_colors_the_status_columns(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".prompt-projects").write_text(
        "one\t/tmp/one\t#111111\n", encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "one").mkdir()
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(
            app=app,
            changes=1,
            behind=2,
            upstream="origin/main",
            branch="main",
        )

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["--color", "always", "check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert "\x1b[1mApp" in output
    assert "\x1b[1;97mone" in output
    assert "\x1b[32m✓" in output
    assert "\x1b[33m1 change" in output
    assert "\x1b[33m2 commits" in output
    separator = next(line for line in output.splitlines() if "─" in line)
    assert "\x1b[" in separator


def test_check_reports_commits_to_push(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

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
    assert "To push" in output
    assert "2 commits" in output
    assert "with commits to push" not in output
    assert "Detail" not in output
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
    assert "Detail" in output
    tracked = _table_fields(output, "tracked")
    assert tracked == [
        "tracked",
        str(tmp_path / "tracked"),
        "x",
        "x",
        "clean",
        "up to date",
        "up to date",
    ]
    assert _table_fields(output, "gone")[7].startswith("missing: ")


def test_check_shows_branch_when_there_is_no_upstream(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app, branch="main")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    output = capsys.readouterr().out
    assert _table_fields(output, "one")[7] == "main"


def test_check_piped_output_omits_blank_detail_column(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app, upstream="origin/main", branch="main")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"one\t{tmp_path / 'one'}\tx\tx\tclean\tup to date\tup to date",
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
    assert _table_fields(captured.out, "one")[2] == "✓"
    assert _table_fields(captured.out, "two")[2] == "✓"
    lines = projects_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "one\t/tmp/one\t#111111"
    assert lines[1].startswith(f"two\t{tmp_path / 'two'}\t#")


def _fake_update_check(app: App, *, fetch: bool = True) -> CheckResult:
    return CheckResult(
        app=app,
        behind=1,
        upstream="origin/main",
        branch="main",
    )


def _add_apps(config_file: Path, tmp_path: Path, *names: str) -> None:
    for name in names:
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


def test_update_pulls_clean_apps_with_remote_updates(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_apps(config_file, tmp_path, "two", "one", "three", "four")

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        if app.name == "two":
            return CheckResult(
                app=app,
                changes=1,
                behind=1,
                upstream="origin/main",
                branch="main",
            )
        if app.name == "three":
            return CheckResult(
                app=app,
                ahead=1,
                behind=1,
                upstream="origin/main",
                branch="main",
            )
        if app.name == "four":
            return CheckResult(app=app, upstream="origin/main", branch="main")
        return _fake_update_check(app)

    prompts: list[tuple[str, bool]] = []

    def fake_confirm(message: str, *, default: bool = False) -> bool:
        prompts.append((message, default))
        return True

    pulled: list[str] = []
    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(cli.click, "confirm", fake_confirm)
    monkeypatch.setattr(cli, "pull_app", lambda app: pulled.append(app.name))
    monkeypatch.setattr(cli, "has_install", lambda _path: False)
    capsys.readouterr()

    assert main(["update"]) == 0

    assert prompts == [("Pull one?", True)]
    assert pulled == ["one"]
    assert "Pulled one" in capsys.readouterr().out


def test_update_asks_before_make_install(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_apps(config_file, tmp_path, "one")
    prompts: list[tuple[str, bool]] = []
    answers = iter([True, True])

    def fake_confirm(message: str, *, default: bool = False) -> bool:
        prompts.append((message, default))
        return next(answers)

    installed: list[str] = []
    monkeypatch.setattr(cli, "check_app", _fake_update_check)
    monkeypatch.setattr(cli.click, "confirm", fake_confirm)
    monkeypatch.setattr(cli, "pull_app", lambda _app: None)
    monkeypatch.setattr(cli, "has_install", lambda _path: True)
    monkeypatch.setattr(
        cli, "run_install", lambda path: installed.append(path.name)
    )
    capsys.readouterr()

    assert main(["update"]) == 0

    assert prompts == [
        ("Pull one?", True),
        ('Run "make install"?', True),
    ]
    assert installed == ["one"]
    output = capsys.readouterr().out
    assert "Pulled one" in output
    assert "Installed one" in output


def test_update_skips_make_install_when_declined(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_apps(config_file, tmp_path, "one")
    answers = iter([True, False])
    installed: list[str] = []

    monkeypatch.setattr(cli, "check_app", _fake_update_check)
    monkeypatch.setattr(
        cli.click,
        "confirm",
        lambda message, *, default=False: next(answers),
    )
    monkeypatch.setattr(cli, "pull_app", lambda _app: None)
    monkeypatch.setattr(cli, "has_install", lambda _path: True)
    monkeypatch.setattr(
        cli, "run_install", lambda path: installed.append(path.name)
    )

    assert main(["update"]) == 0
    assert installed == []


def test_update_skips_a_declined_pull(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_apps(config_file, tmp_path, "one")
    pulled: list[str] = []

    monkeypatch.setattr(cli, "check_app", _fake_update_check)
    monkeypatch.setattr(
        cli.click, "confirm", lambda message, *, default=False: False
    )
    monkeypatch.setattr(cli, "pull_app", lambda app: pulled.append(app.name))

    assert main(["update"]) == 0
    assert pulled == []


def test_update_continues_after_a_pull_failure(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_apps(config_file, tmp_path, "one", "two")
    pulled: list[str] = []

    def fake_pull(app: App) -> None:
        if app.name == "one":
            raise SuiteError("boom")
        pulled.append(app.name)

    monkeypatch.setattr(cli, "check_app", _fake_update_check)
    monkeypatch.setattr(
        cli.click, "confirm", lambda message, *, default=False: True
    )
    monkeypatch.setattr(cli, "pull_app", fake_pull)
    monkeypatch.setattr(cli, "has_install", lambda _path: False)
    capsys.readouterr()

    assert main(["update"]) == 1

    captured = capsys.readouterr()
    assert "error: one: boom" in captured.err
    assert pulled == ["two"]


def test_update_reports_a_make_install_failure(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_apps(config_file, tmp_path, "one")

    def fail(_path: Path) -> None:
        raise SuiteError("boom")

    monkeypatch.setattr(cli, "check_app", _fake_update_check)
    monkeypatch.setattr(
        cli.click, "confirm", lambda message, *, default=False: True
    )
    monkeypatch.setattr(cli, "pull_app", lambda _app: None)
    monkeypatch.setattr(cli, "has_install", lambda _path: True)
    monkeypatch.setattr(cli, "run_install", fail)
    capsys.readouterr()

    assert main(["update"]) == 1

    captured = capsys.readouterr()
    assert "error: one: boom" in captured.err
    assert "Installed one" not in captured.out


def test_update_skips_apps_with_fetch_errors(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_apps(config_file, tmp_path, "one")

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(
            app=app,
            behind=1,
            upstream="origin/main",
            branch="main",
            fetch_error="could not resolve host",
        )

    prompts: list[str] = []
    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(
        cli.click,
        "confirm",
        lambda message, *, default=False: prompts.append(message) or True,
    )
    capsys.readouterr()

    assert main(["update"]) == 0

    captured = capsys.readouterr()
    assert "warning: one: could not resolve host" in captured.err
    assert "No apps with remote updates to pull." in captured.out
    assert prompts == []


def test_update_reports_no_apps_when_piped(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_apps(config_file, tmp_path, "one")

    def fake_check_app(app: App, *, fetch: bool = True) -> CheckResult:
        return CheckResult(app=app, upstream="origin/main", branch="main")

    monkeypatch.setattr(cli, "check_app", fake_check_app)
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["update"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "No apps with remote updates to pull." in captured.err


def test_update_without_apps(
    config_file: Path,
    tty_output: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["update"]) == 0

    assert "No apps configured." in capsys.readouterr().out


def test_config_path(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config"]) == 0

    output = capsys.readouterr().out.strip()
    assert output == str(config_file)
    assert "\x1b" not in output
    assert not config_file.exists()


def test_short_help_flag(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["-h"]) == 0

    output = capsys.readouterr().out
    assert "Usage: suite" in output
    assert "--completions" in output
    assert "--config" in output
    assert not config_file.exists()


def test_subcommand_short_help_flag(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "-h"]) == 0

    output = capsys.readouterr().out
    assert "Usage: suite check" in output
    assert not config_file.exists()


def test_version_matches_pyproject(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    expected = f"suite, version {pyproject['project']['version']}"

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

    script_path = data_home / "bash-completion" / "completions" / "suite.bash"
    assert script_path.is_file()
    script = script_path.read_text(encoding="utf-8")
    assert "Generated by `suite --completions`" in script
    assert (
        "complete -o nosort -o bashdefault -o default "
        "-F _suite_complete suite" in script
    )

    captured = capsys.readouterr()
    assert captured.out.strip() == str(script_path)
    assert f"source {script_path}" in captured.err
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


def test_completions_overwrites_an_existing_script(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    script_path = data_home / "bash-completion" / "completions" / "suite.bash"
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
    assert (
        main(
            [
                "add",
                "one",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )
    capsys.readouterr()

    def interrupted(app: App, *, fetch: bool = True) -> CheckResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "check_app", interrupted)

    assert main(["check", "--no-fetch"]) == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Traceback" not in captured.out


def _add_one(config_file: Path, tmp_path: Path, name: str = "one") -> None:
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


def _fake_check(app: App, *, fetch: bool = True) -> CheckResult:
    return CheckResult(
        app=app,
        changes=1,
        behind=2,
        upstream="origin/main",
        branch="main",
    )


def test_color_never_emits_no_ansi(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_one(config_file, tmp_path)
    monkeypatch.setattr(cli, "check_app", _fake_check)
    capsys.readouterr()

    assert main(["--color", "never", "check", "--no-fetch"]) == 0

    captured = capsys.readouterr()
    assert "\x1b" not in captured.out
    assert "\x1b" not in captured.err


def test_color_auto_emits_no_ansi_when_captured(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_one(config_file, tmp_path)
    monkeypatch.setattr(cli, "check_app", _fake_check)
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    assert "\x1b" not in capsys.readouterr().out


def test_force_color_is_honored_when_auto(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_one(config_file, tmp_path)
    monkeypatch.setattr(cli, "check_app", _fake_check)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    assert "\x1b" in capsys.readouterr().out


def test_no_color_is_honored_when_auto(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_one(config_file, tmp_path)
    monkeypatch.setattr(cli, "check_app", _fake_check)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    capsys.readouterr()

    assert main(["check", "--no-fetch"]) == 0

    assert "\x1b" not in capsys.readouterr().out


def test_color_always_wins_over_no_color(
    config_file: Path,
    tty_output: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_one(config_file, tmp_path)
    monkeypatch.setattr(cli, "check_app", _fake_check)
    monkeypatch.setenv("NO_COLOR", "1")
    capsys.readouterr()

    assert main(["--color", "always", "check", "--no-fetch"]) == 0

    assert "\x1b" in capsys.readouterr().out


def test_user_markup_is_escaped(
    config_file: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "one").mkdir()

    assert (
        main(
            [
                "add",
                "[red]one[/red]",
                str(tmp_path / "one"),
                "--remote",
                "git@example.com:one.git",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "[red]one[/red]" in output
    assert "\x1b" not in output


def test_config_does_not_create_the_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.chdir(tmp_path)

    assert main(["--config"]) == 0

    assert not config_home.exists()
    assert capsys.readouterr().out.strip() == str(
        config_home / "suite" / "config.toml"
    )


@pytest.mark.parametrize(
    "command", ["add", "check", "install", "remove", "update"]
)
def test_every_subcommand_has_short_help(
    command: str,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([command, "-h"]) == 0

    output = capsys.readouterr().out
    assert "Usage: suite" in output
    assert not config_file.exists()


def test_version_has_no_ansi(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--version"]) == 0

    output = capsys.readouterr().out
    assert "\x1b" not in output


def test_invalid_toml_is_a_clean_error(
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file.write_text("app = [", encoding="utf-8")

    assert main(["check"]) == 2

    error = capsys.readouterr().err
    assert "invalid TOML" in error
    assert str(config_file) in error
    assert "\x1b" not in error


def test_unknown_config_keys_warn(
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file.write_text("unknown = true\n", encoding="utf-8")

    assert main([]) == 0

    assert "unknown configuration key" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["check", "--help"],
        ["add", "--help"],
        ["install", "--help"],
        ["remove", "--help"],
        ["update", "--help"],
    ],
)
def test_long_help_flags(
    args: list[str],
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(args) == 0

    output = capsys.readouterr().out
    assert "Usage: suite" in output
    assert "\x1b" not in output
    assert not config_file.exists()
