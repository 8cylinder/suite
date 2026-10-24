from pathlib import Path

import pytest

from suite.models import App
from suite.prompt_projects import add_projects, load_projects


def test_load_projects_reads_tsv(tmp_path: Path) -> None:
    projects_file = tmp_path / ".prompt-projects"
    projects_file.write_text(
        "# comment\n\none\t/tmp/one\t#abcdef\nwrong\n\t/tmp/no-name\t#ffffff\ntwo\t/tmp/two\n",
        encoding="utf-8",
    )

    projects = load_projects(projects_file)

    assert list(projects) == ["one", "two"]
    assert projects["one"].path == Path("/tmp/one")
    assert projects["one"].color == "#abcdef"
    assert projects["two"].path == Path("/tmp/two")
    assert projects["two"].color == ""


def test_load_projects_returns_empty_when_missing(tmp_path: Path) -> None:
    assert load_projects(tmp_path / "missing") == {}


def test_add_projects_appends_only_missing_apps(tmp_path: Path) -> None:
    projects_file = tmp_path / ".prompt-projects"
    projects_file.write_text("one\t/tmp/one\t#111111", encoding="utf-8")
    apps = [
        App(name="one", local_dir=Path("/tmp/one")),
        App(name="two", local_dir=Path("/tmp/two")),
    ]

    added = add_projects(apps, projects_file)

    assert [app.name for app in added] == ["two"]
    lines = projects_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "one\t/tmp/one\t#111111"
    assert lines[1].startswith("two\t/tmp/two\t#")
    assert add_projects(apps, projects_file) == []


def test_add_projects_creates_the_file(tmp_path: Path) -> None:
    projects_file = tmp_path / "nested" / ".prompt-projects"

    added = add_projects([App(name="one", local_dir=Path("/tmp/one"))], projects_file)

    assert [app.name for app in added] == ["one"]
    assert projects_file.is_file()


def test_add_projects_preserves_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "dotfig" / ".prompt-projects"
    target.parent.mkdir()
    target.write_text("", encoding="utf-8")
    link = tmp_path / ".prompt-projects"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not supported")

    add_projects([App(name="one", local_dir=Path("/tmp/one"))], link)

    assert link.is_symlink()
    assert "one\t/tmp/one\t#" in target.read_text(encoding="utf-8")
