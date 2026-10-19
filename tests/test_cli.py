from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from suite.cli import main


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
    assert main(["add", "cm", "--dir", str(local_dir), "--remote", "git@example.com:cm.git"]) == 0

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
    assert main(["add", "cm", "--dir", str(tmp_path / "cm")]) == 0
    capsys.readouterr()

    assert main(["add", "cm", "--dir", str(tmp_path / "other")]) == 2

    assert "already exists" in capsys.readouterr().err


def test_check_reports_missing_app(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["add", "missing-app", "--dir", str(tmp_path / "missing")]) == 0
    capsys.readouterr()

    exit_code = main(["check", "--no-fetch"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "missing-app" in captured.out
    assert "missing:" in captured.out
    assert "1 with problems" in captured.out


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
