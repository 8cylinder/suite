from pathlib import Path

import pytest
import yaml

from suite.config import Config, ConfigError, config_path_from_env, display_path
from suite.models import App

ORG = """\
* Development apps
** cm
Generate a commit message.
remote: =git@example.com:cm.git=
** tether
Run agents.
remote: =git@example.com:tether.git=
"""


def test_first_run_creates_and_seeds_config(tmp_path: Path) -> None:
    org_file = tmp_path / "suite.org"
    org_file.write_text(ORG, encoding="utf-8")
    config_file = tmp_path / "config" / "config.yaml"

    config = Config.load(config_file, org_path=org_file)

    assert config.created is True
    assert config_file.is_file()
    assert [app.name for app in config.apps] == ["cm", "tether"]
    assert config.apps[0].local_dir == Path.home() / "dev" / "cm"
    assert config.apps[0].remote == "git@example.com:cm.git"
    assert config.apps[0].description == "Generate a commit message."

    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert data["apps_root"] == "~/dev"
    assert data["apps"][0] == {
        "name": "cm",
        "local_dir": "~/dev/cm",
        "remote": "git@example.com:cm.git",
        "description": "Generate a commit message.",
    }

    reloaded = Config.load(config_file, org_path=org_file)
    assert reloaded.created is False
    assert reloaded.apps == config.apps


def test_existing_checkout_is_detected(tmp_path: Path) -> None:
    org_file = tmp_path / "suite.org"
    org_file.write_text(ORG, encoding="utf-8")
    (tmp_path / "cm").mkdir()

    config = Config.load(tmp_path / "config.yaml", org_path=org_file)

    assert config.apps[0].local_dir == tmp_path / "cm"


def test_sync_adds_new_apps_and_updates_metadata_but_keeps_local_dir(
    tmp_path: Path,
) -> None:
    org_file = tmp_path / "suite.org"
    org_file.write_text(ORG, encoding="utf-8")
    config = Config.load(tmp_path / "config.yaml", org_path=org_file)

    custom = tmp_path / "custom-cm"
    config.apps[0] = App(
        name="cm",
        local_dir=custom,
        remote="git@example.com:old.git",
        description="Old description.",
    )
    config.save()

    org_file.write_text(
        ORG.replace("Generate a commit message.", "New description.")
        + "** new-app\nA new application.\n",
        encoding="utf-8",
    )
    (tmp_path / "new-app").mkdir()

    stats = config.sync_from_org(org_file)

    assert stats.added == ("new-app",)
    assert stats.updated == ("cm",)
    assert config.apps[0].local_dir == custom
    assert config.apps[0].remote == "git@example.com:cm.git"
    assert config.apps[0].description == "New description."
    assert config.apps[-1].local_dir == tmp_path / "new-app"


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
    config = Config.load(tmp_path / "config.yaml", org_path=tmp_path / "missing.org")
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


def test_config_path_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "custom" / "config.yaml"
    monkeypatch.setenv("SUITE_CONFIG", str(target))

    assert config_path_from_env() == target


def test_display_path_abbreviates_home() -> None:
    assert display_path(Path.home() / "dev" / "cm") == "~/dev/cm"
    assert display_path(Path("/opt/apps/cm")) == "/opt/apps/cm"
