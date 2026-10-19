from pathlib import Path

from suite.org import parse_org


def test_parse_suite_org() -> None:
    text = (Path(__file__).parents[1] / "suite.org").read_text(encoding="utf-8")

    entries = parse_org(text)

    assert [entry.name for entry in entries] == [
        "cm",
        "tether",
        "prism",
        "dotfig",
        "cyborg",
        "prompt",
        "sink",
        "kompressor",
        "do-until",
        "chopper",
    ]
    assert entries[0].remote == "git@github.com:8cylinder/commit.git"
    assert entries[0].description == (
        "Generate a git commit message from the working-tree diff using a pluggable AI provider."
    )
    assert entries[-1].remote == "git@github.com:8cylinder/chopper.git"


def test_parse_local_override_and_multiline_description() -> None:
    text = """\
* Development apps
** demo
A description
that spans lines.
remote: =git@example.com:demo.git=
local: =~/code/demo=
** bare
remote: git@example.com:bare.git
"""

    entries = parse_org(text)

    assert entries[0].description == "A description that spans lines."
    assert entries[0].local_dir == Path.home() / "code" / "demo"
    assert entries[1].name == "bare"
    assert entries[1].local_dir is None
    assert entries[1].description is None


def test_ignores_top_level_and_deeper_headings() -> None:
    text = """\
* Apps
*** Not an app
** Real app
Description.
"""

    entries = parse_org(text)

    assert [entry.name for entry in entries] == ["Real app"]
