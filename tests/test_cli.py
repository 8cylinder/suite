from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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
    with pytest.raises(SystemExit) as exc_info:
        main(["add", "cm"])
    assert exc_info.value.code == 2
    assert "path" in capsys.readouterr().err

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
