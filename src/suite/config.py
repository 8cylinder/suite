from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import platformdirs
import yaml

from .errors import SuiteError
from .models import App, SuiteEntry
from .org import parse_org

CONFIG_ENV = "SUITE_CONFIG"
CONFIG_FILENAME = "config.yaml"
DEFAULT_APPS_ROOT = Path("~/dev")

CONFIG_HEADER = """\
# suite configuration
# Edit local_dir values to point at each application's checkout.
"""


class _ConfigDumper(yaml.SafeDumper):
    """Keep sequences indented under their parent key."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


class ConfigError(SuiteError):
    """The configuration file is missing, invalid, or cannot be written."""


@dataclass(frozen=True, slots=True)
class SyncStats:
    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()


@dataclass
class Config:
    """The suite database, stored as YAML."""

    path: Path
    apps_root: Path
    apps: list[App] = field(default_factory=list)
    created: bool = False

    @classmethod
    def load(cls, path: Path | None = None, *, org_path: Path | None = None) -> Config:
        """Load the config, creating it from suite.org on first run."""
        config_path = config_path_from_env() if path is None else path.expanduser()
        if config_path.is_dir():
            raise ConfigError(f"config path is a directory: {config_path}")
        if not config_path.exists():
            org_file = org_path if org_path is not None else Path.cwd() / "suite.org"
            config = cls(path=config_path, apps_root=DEFAULT_APPS_ROOT.expanduser())
            if org_file.is_file():
                config.sync_from_org(org_file)
            config.save()
            config.created = True
            return config

        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"could not read {config_path}: {exc}") from exc
        return cls._from_yaml(config_path, text)

    @classmethod
    def _from_yaml(cls, path: Path, text: str) -> Config:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
        if data is None:
            raise ConfigError(f"config file is empty: {path}")
        if not isinstance(data, Mapping):
            raise ConfigError(f"config file must contain a mapping: {path}")

        raw = cast(Mapping[str, Any], data)
        base = path.parent
        apps_root_raw = raw.get("apps_root", str(DEFAULT_APPS_ROOT))
        if not isinstance(apps_root_raw, str) or not apps_root_raw.strip():
            raise ConfigError(f"'apps_root' must be a non-empty string in {path}")

        apps_raw = raw.get("apps", [])
        if apps_raw is None:
            apps_raw = []
        if not isinstance(apps_raw, list):
            raise ConfigError(f"'apps' must be a list in {path}")

        apps: list[App] = []
        seen: set[str] = set()
        for index, item in enumerate(apps_raw, start=1):
            if not isinstance(item, Mapping):
                raise ConfigError(f"app #{index} must be a mapping in {path}")
            entry = cast(Mapping[str, Any], item)
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError(f"app #{index} is missing a valid 'name' in {path}")
            name = name.strip()
            if name in seen:
                raise ConfigError(f"duplicate app name: {name!r} in {path}")
            seen.add(name)

            local_dir_raw = entry.get("local_dir")
            if not isinstance(local_dir_raw, str) or not local_dir_raw.strip():
                raise ConfigError(f"app {name!r} is missing a valid 'local_dir' in {path}")
            remote = _optional_string(entry.get("remote"), "remote", name, path)
            description = _optional_string(entry.get("description"), "description", name, path)
            apps.append(
                App(
                    name=name,
                    local_dir=_resolve_path(local_dir_raw, base),
                    remote=remote,
                    description=description,
                )
            )
        return cls(path=path, apps_root=_resolve_path(apps_root_raw, base), apps=apps)

    def save(self) -> None:
        data = {
            "apps_root": _encode_path(self.apps_root),
            "apps": [_app_to_mapping(app) for app in self.apps],
        }
        try:
            text = CONFIG_HEADER + yaml.dump(
                data,
                Dumper=_ConfigDumper,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
                width=1000,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            raise ConfigError(f"could not write {self.path}: {exc}") from exc

    def find(self, name: str) -> App | None:
        return next((app for app in self.apps if app.name == name), None)

    def add_app(self, app: App) -> None:
        if self.find(app.name) is not None:
            raise ConfigError(f"app {app.name!r} already exists in {self.path}")
        self.apps.append(app)

    def remove_app(self, name: str) -> App:
        app = self.find(name)
        if app is None:
            raise ConfigError(f"app {name!r} is not configured")
        self.apps.remove(app)
        return app

    def sync_from_org(self, org_file: Path) -> SyncStats:
        """Merge apps from an org file, preserving existing local directories."""
        try:
            text = org_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"could not read {org_file}: {exc}") from exc

        added: list[str] = []
        updated: list[str] = []
        for entry in parse_org(text):
            existing = self.find(entry.name)
            if existing is None:
                self.apps.append(
                    App(
                        name=entry.name,
                        local_dir=_new_local_dir(entry, self.apps_root, org_file),
                        remote=entry.remote,
                        description=entry.description,
                    )
                )
                added.append(entry.name)
                continue

            remote = entry.remote if entry.remote is not None else existing.remote
            description = (
                entry.description if entry.description is not None else existing.description
            )
            if remote != existing.remote or description != existing.description:
                index = self.apps.index(existing)
                self.apps[index] = App(
                    name=existing.name,
                    local_dir=existing.local_dir,
                    remote=remote,
                    description=description,
                )
                updated.append(entry.name)

        return SyncStats(added=tuple(added), updated=tuple(updated))


def config_path_from_env() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    directory = platformdirs.user_config_dir("suite", appauthor=False)
    return Path(directory) / CONFIG_FILENAME


def display_path(path: Path) -> str:
    """Render a path with the home directory abbreviated to ``~``."""
    try:
        relative = path.expanduser().relative_to(Path.home())
    except ValueError:
        return str(path)
    return "~" if str(relative) == "." else f"~/{relative.as_posix()}"


def absolute_path(path: Path, *, base: Path | None = None) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return ((base if base is not None else Path.cwd()) / expanded).resolve()


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _encode_path(path: Path) -> str:
    return display_path(path)


def _optional_string(value: object, field_name: str, app_name: str, path: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"app {app_name!r} has an invalid '{field_name}' in {path}")
    value = value.strip()
    return value or None


def _app_to_mapping(app: App) -> dict[str, str]:
    mapping = {"name": app.name, "local_dir": _encode_path(app.local_dir)}
    if app.remote:
        mapping["remote"] = app.remote
    if app.description:
        mapping["description"] = app.description
    return mapping


def _new_local_dir(entry: SuiteEntry, apps_root: Path, org_file: Path) -> Path:
    if entry.local_dir is not None:
        return absolute_path(entry.local_dir)
    for base in (org_file.parent, Path.cwd(), apps_root):
        candidate = base / entry.name
        if candidate.is_dir():
            return candidate
    return apps_root / entry.name
