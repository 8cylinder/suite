from pathlib import Path

import pytest
import yaml

from suite.config import (
    Config,
    ConfigError,
    absolute_path,
    config_path_from_env,
    display_path,
    stored_path,
)
from suite.models import App


def test_first_run_creates_an_empty_config(tmp_path: Path) -> None:
    config_file = tmp_path / "config" / "config.yaml"

    config = Config.load(config_file)

    assert config.created is True
    assert config_file.is_file()
    assert config.apps == []

    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert data["apps_root"] == "~/dev"
    assert data["apps"] == []

    reloaded = Config.load(config_file)
    assert reloaded.created is False
    assert reloaded.apps == []


def test_load_reads_app_kind(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """\
apps:
  - name: bin
    local_dir: /tmp/bin
    kind: misc
  - name: cm
    local_dir: /tmp/cm
""",
        encoding="utf-8",
    )

    config = Config.load(config_file)

    assert config.apps[0].kind == "misc"
    assert config.apps[1].kind == "app"


def test_load_rejects_an_invalid_kind(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """\
apps:
  - name: bin
    local_dir: /tmp/bin
    kind: collection
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="invalid 'kind'"):
        Config.load(config_file)


def test_save_only_writes_non_default_kind(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "config.yaml")
    config.add_app(App(name="cm", local_dir=tmp_path / "cm"))
    config.add_app(App(name="bin", local_dir=tmp_path / "bin", kind="misc"))
    config.save()

    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["apps"][0] == {"name": "cm", "local_dir": str(tmp_path / "cm")}
    assert data["apps"][1] == {
        "name": "bin",
        "local_dir": str(tmp_path / "bin"),
        "kind": "misc",
    }


def test_load_rejects_duplicate_names(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """\
apps:
  - name: cm
    local_dir: /tmp/cm
  - name: cm
    local_dir: /tmp/cm2
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate app name"):
        Config.load(config_file)


def test_load_rejects_invalid_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("apps: [", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid YAML"):
        Config.load(config_file)


def test_add_and_remove_app(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "config.yaml")
    app = App(name="cm", local_dir=tmp_path / "cm")
    config.add_app(app)
    config.save()

    assert Config.load(tmp_path / "config.yaml").find("cm") == app
    with pytest.raises(ConfigError, match="already exists"):
        config.add_app(app)

    removed = config.remove_app("cm")
    assert removed == app
    assert config.apps == []
    with pytest.raises(ConfigError, match="not configured"):
        config.remove_app("cm")


def test_add_app_can_overwrite_in_place(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "config.yaml")
    original = App(name="cm", local_dir=tmp_path / "cm")
    replacement = App(name="cm", local_dir=tmp_path / "cm2", kind="misc")
    config.add_app(original)
    config.add_app(replacement, overwrite=True)

    assert config.apps == [replacement]
    config.save()
    assert Config.load(tmp_path / "config.yaml").apps == [replacement]


def test_config_path_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "custom" / "config.yaml"
    monkeypatch.setenv("SUITE_CONFIG", str(target))

    assert config_path_from_env() == target


def test_load_expands_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """\
apps_root: $HOME/dev
apps:
  - name: cm
    local_dir: ${HOME}/projects/cm
""",
        encoding="utf-8",
    )

    config = Config.load(config_file)

    assert config.apps_root == home / "dev"
    assert config.apps[0].local_dir == home / "projects" / "cm"


def test_absolute_path_expands_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert absolute_path(Path("$HOME/Projects/cm")) == home / "Projects" / "cm"


def test_display_path_is_absolute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert display_path(Path("~/dev/cm")) == str(home / "dev" / "cm")
    assert display_path(Path("/opt/apps/cm")) == "/opt/apps/cm"


def test_stored_path_abbreviates_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert stored_path(home / "dev" / "cm") == "~/dev/cm"
    assert stored_path(Path("/opt/apps/cm")) == "/opt/apps/cm"


def test_save_stores_home_paths_with_tilde(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = Config.load(tmp_path / "config.yaml")
    config.add_app(App(name="cm", local_dir=home / "dev" / "cm"))
    config.add_app(App(name="bin", local_dir=tmp_path / "bin"))
    config.save()

    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert data["apps_root"] == "~/dev"
    assert data["apps"][0]["local_dir"] == "~/dev/cm"
    assert data["apps"][1]["local_dir"] == str(tmp_path / "bin")
