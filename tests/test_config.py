import tomllib
from pathlib import Path
from typing import Any

import pytest

from suite.config import (
    Config,
    ConfigError,
    absolute_path,
    config_path,
    display_path,
    stored_path,
)
from suite.models import App


def _read(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_first_run_creates_an_empty_config(tmp_path: Path) -> None:
    config_file = tmp_path / "config" / "config.toml"

    config = Config.load(config_file)

    assert config.created is True
    assert config_file.is_file()
    assert config.apps == []
    assert config_file.stat().st_mode & 0o777 == 0o600

    data = _read(config_file)
    assert data["apps_root"] == "~/dev"
    assert "app" not in data

    reloaded = Config.load(config_file)
    assert reloaded.created is False
    assert reloaded.apps == []


def test_load_reads_app_kind(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """\
[[app]]
name = "bin"
local_dir = "/tmp/bin"
kind = "misc"

[[app]]
name = "cm"
local_dir = "/tmp/cm"
""",
        encoding="utf-8",
    )

    config = Config.load(config_file)

    assert config.apps[0].kind == "misc"
    assert config.apps[1].kind == "app"


def test_load_rejects_an_invalid_kind(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """\
[[app]]
name = "bin"
local_dir = "/tmp/bin"
kind = "collection"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="invalid 'kind'"):
        Config.load(config_file)


def test_save_only_writes_non_default_kind(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "config.toml")
    config.add_app(App(name="cm", local_dir=tmp_path / "cm"))
    config.add_app(App(name="bin", local_dir=tmp_path / "bin", kind="misc"))
    config.save()

    data = _read(tmp_path / "config.toml")
    assert data["app"] == [
        {"name": "cm", "local_dir": str(tmp_path / "cm")},
        {
            "name": "bin",
            "local_dir": str(tmp_path / "bin"),
            "kind": "misc",
        },
    ]


def test_load_rejects_duplicate_names(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """\
[[app]]
name = "cm"
local_dir = "/tmp/cm"

[[app]]
name = "cm"
local_dir = "/tmp/cm2"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate app name"):
        Config.load(config_file)


def test_load_rejects_invalid_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("app = [", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid TOML"):
        Config.load(config_file)


def test_add_and_remove_app(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "config.toml")
    app = App(name="cm", local_dir=tmp_path / "cm")
    config.add_app(app)
    config.save()

    assert Config.load(tmp_path / "config.toml").find("cm") == app
    with pytest.raises(ConfigError, match="already exists"):
        config.add_app(app)

    removed = config.remove_app("cm")
    assert removed == app
    assert config.apps == []
    with pytest.raises(ConfigError, match="not configured"):
        config.remove_app("cm")


def test_add_app_can_overwrite_in_place(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "config.toml")
    original = App(name="cm", local_dir=tmp_path / "cm")
    replacement = App(name="cm", local_dir=tmp_path / "cm2", kind="misc")
    config.add_app(original)
    config.add_app(replacement, overwrite=True)

    assert config.apps == [replacement]
    config.save()
    assert Config.load(tmp_path / "config.toml").apps == [replacement]


def test_config_path_uses_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert config_path() == tmp_path / "suite" / "config.toml"


def test_config_path_falls_back_to_dot_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert config_path() == tmp_path / ".config" / "suite" / "config.toml"


def test_load_expands_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """\
apps_root = "$HOME/dev"

[[app]]
name = "cm"
local_dir = "${HOME}/projects/cm"
""",
        encoding="utf-8",
    )

    config = Config.load(config_file)

    assert config.apps_root == home / "dev"
    assert config.apps[0].local_dir == home / "projects" / "cm"


def test_relative_paths_resolve_against_the_config_directory(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """\
apps_root = "dev"

[[app]]
name = "cm"
local_dir = "projects/cm"
""",
        encoding="utf-8",
    )

    config = Config.load(config_file)

    assert config.apps_root == tmp_path / "dev"
    assert config.apps[0].local_dir == tmp_path / "projects" / "cm"


def test_absolute_path_expands_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert absolute_path(Path("$HOME/Projects/cm")) == home / "Projects" / "cm"


def test_display_path_is_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert display_path(Path("~/dev/cm")) == str(home / "dev" / "cm")
    assert display_path(Path("/opt/apps/cm")) == "/opt/apps/cm"


def test_stored_path_abbreviates_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert stored_path(home / "dev" / "cm") == "~/dev/cm"
    assert stored_path(home) == "~"
    assert stored_path(Path("/opt/apps/cm")) == "/opt/apps/cm"


def test_save_stores_home_paths_with_tilde(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = Config.load(tmp_path / "config.toml")
    config.add_app(App(name="cm", local_dir=home / "dev" / "cm"))
    config.add_app(App(name="bin", local_dir=tmp_path / "bin"))
    config.save()

    data = _read(tmp_path / "config.toml")
    assert data["apps_root"] == "~/dev"
    assert data["app"][0]["local_dir"] == "~/dev/cm"
    assert data["app"][1]["local_dir"] == str(tmp_path / "bin")


def test_load_warns_about_unknown_keys(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """\
unknown = true

[[app]]
name = "cm"
local_dir = "/tmp/cm"
extra = "value"
""",
        encoding="utf-8",
    )

    config = Config.load(config_file)

    assert len(config.warnings) == 2
    assert "unknown" in config.warnings[0]
    assert "extra" in config.warnings[1]


def test_load_rejects_non_string_apps_root(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("apps_root = 3\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="'apps_root'"):
        Config.load(config_file)


def test_load_rejects_non_list_app(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('app = "nope"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="'app' must be a list"):
        Config.load(config_file)


def test_load_rejects_non_mapping_app(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('app = ["nope"]\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="must be a mapping"):
        Config.load(config_file)


def test_load_rejects_missing_name(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('[[app]]\nlocal_dir = "/tmp/cm"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="valid 'name'"):
        Config.load(config_file)


def test_load_rejects_missing_local_dir(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('[[app]]\nname = "cm"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="valid 'local_dir'"):
        Config.load(config_file)


def test_load_rejects_invalid_remote(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[[app]]\nname = "cm"\nlocal_dir = "/tmp/cm"\nremote = 3\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="invalid 'remote'"):
        Config.load(config_file)


def test_load_rejects_a_directory_config_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="is a directory"):
        Config.load(tmp_path)


def test_save_escapes_toml_strings(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "config.toml")
    config.add_app(
        App(
            name="cm",
            local_dir=tmp_path / "cm",
            description='say "hello"\\world',
        )
    )
    config.save()

    assert Config.load(tmp_path / "config.toml").apps[0].description == (
        'say "hello"\\world'
    )
