from __future__ import annotations

import json
import os
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import platformdirs

from .errors import SuiteError
from .models import App, AppKind

CONFIG_FILENAME = "config.toml"
DEFAULT_APPS_ROOT = Path("~/dev")

CONFIG_HEADER = """\
# suite configuration
# Edit local_dir values to point at each application's checkout.
"""

_TOP_LEVEL_KEYS = frozenset({"apps_root", "app"})
_APP_KEYS = frozenset({"name", "local_dir", "remote", "description", "kind"})


class ConfigError(SuiteError):
    """The configuration file is missing, invalid, or cannot be written."""


@dataclass
class Config:
    """The suite database, stored as TOML."""

    path: Path
    apps_root: Path
    apps: list[App] = field(default_factory=list)
    created: bool = False
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Load the config, creating an empty one on first run."""
        config_file = config_path() if path is None else _expand_path(path)
        if config_file.is_dir():
            raise ConfigError(f"config path is a directory: {config_file}")
        if not config_file.exists():
            config = cls(
                path=config_file,
                apps_root=DEFAULT_APPS_ROOT.expanduser(),
            )
            config.save()
            config.created = True
            return config

        try:
            with config_file.open("rb") as handle:
                data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {config_file}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"could not read {config_file}: {exc}") from exc
        return cls._from_mapping(config_file, data)

    @classmethod
    def _from_mapping(cls, path: Path, data: Mapping[str, Any]) -> Config:
        warnings = [
            f"unknown configuration key {key!r} in {path}; ignoring"
            for key in data
            if key not in _TOP_LEVEL_KEYS
        ]
        base = path.parent
        apps_root_raw = data.get("apps_root", str(DEFAULT_APPS_ROOT))
        if not isinstance(apps_root_raw, str) or not apps_root_raw.strip():
            raise ConfigError(
                f"'apps_root' must be a non-empty string in {path}"
            )

        app_entries = data.get("app", [])
        if app_entries is None:
            app_entries = []
        if not isinstance(app_entries, list):
            raise ConfigError(f"'app' must be a list in {path}")

        apps: list[App] = []
        seen: set[str] = set()
        for index, item in enumerate(app_entries, start=1):
            if not isinstance(item, Mapping):
                raise ConfigError(f"app #{index} must be a mapping in {path}")
            entry = cast(Mapping[str, Any], item)
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError(
                    f"app #{index} is missing a valid 'name' in {path}"
                )
            name = name.strip()
            if name in seen:
                raise ConfigError(f"duplicate app name: {name!r} in {path}")
            seen.add(name)
            warnings.extend(
                f"unknown configuration key {key!r} for app {name!r} "
                f"in {path}; ignoring"
                for key in entry
                if key not in _APP_KEYS
            )

            local_dir_raw = entry.get("local_dir")
            if not isinstance(local_dir_raw, str) or not local_dir_raw.strip():
                raise ConfigError(
                    f"app {name!r} is missing a valid 'local_dir' in {path}"
                )
            remote = _optional_string(entry.get("remote"), "remote", name, path)
            description = _optional_string(
                entry.get("description"), "description", name, path
            )
            kind = _parse_kind(entry.get("kind"), name, path)
            apps.append(
                App(
                    name=name,
                    local_dir=_resolve_path(local_dir_raw, base),
                    remote=remote,
                    description=description,
                    kind=kind,
                )
            )
        return cls(
            path=path,
            apps_root=_resolve_path(apps_root_raw, base),
            apps=apps,
            warnings=warnings,
        )

    def save(self) -> None:
        text = _render(self)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                text=True,
            )
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(text)
                Path(name).replace(self.path)
            except BaseException:
                Path(name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise ConfigError(f"could not write {self.path}: {exc}") from exc

    def find(self, name: str) -> App | None:
        return next((app for app in self.apps if app.name == name), None)

    def add_app(self, app: App, *, overwrite: bool = False) -> None:
        existing = self.find(app.name)
        if existing is not None:
            if not overwrite:
                raise ConfigError(
                    f"app {app.name!r} already exists in {self.path}"
                )
            self.apps[self.apps.index(existing)] = app
            return
        self.apps.append(app)

    def remove_app(self, name: str) -> App:
        app = self.find(name)
        if app is None:
            raise ConfigError(f"app {name!r} is not configured")
        self.apps.remove(app)
        return app


def config_path() -> Path:
    """Return the platform config file path."""
    directory = platformdirs.user_config_dir("suite", appauthor=False)
    return (Path(directory) / CONFIG_FILENAME).expanduser().absolute()


def display_path(path: Path) -> str:
    """Render a path as an absolute path."""
    return str(path.expanduser().absolute())


def stored_path(path: Path) -> str:
    """Render a path for the config, abbreviating the home directory."""
    expanded = path.expanduser()
    try:
        relative = expanded.relative_to(Path.home())
    except ValueError:
        return display_path(expanded)
    return "~" if str(relative) == "." else f"~/{relative.as_posix()}"


def absolute_path(path: Path, *, base: Path | None = None) -> Path:
    expanded = _expand_path(path)
    if expanded.is_absolute():
        return expanded
    return ((base if base is not None else Path.cwd()) / expanded).resolve()


def _render(config: Config) -> str:
    lines: list[str] = [str(line) for line in CONFIG_HEADER.splitlines()]
    lines.append(f"apps_root = {_toml_string(stored_path(config.apps_root))}")
    for app in config.apps:
        lines.append("")
        lines.append("[[app]]")
        lines.append(f"name = {_toml_string(app.name)}")
        lines.append(f"local_dir = {_toml_string(stored_path(app.local_dir))}")
        if app.remote:
            lines.append(f"remote = {_toml_string(app.remote)}")
        if app.description:
            lines.append(f"description = {_toml_string(app.description)}")
        if app.kind == "misc":
            lines.append('kind = "misc"')
    return "\n".join(lines) + "\n"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _resolve_path(value: str, base: Path) -> Path:
    path = _expand_path(value)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _expand_path(value: str | Path) -> Path:
    """Expand environment variables and a leading ``~`` in a path."""
    return Path(os.path.expandvars(value)).expanduser()


def _optional_string(
    value: object, field_name: str, app_name: str, path: Path
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(
            f"app {app_name!r} has an invalid '{field_name}' in {path}"
        )
    value = value.strip()
    return value or None


def _parse_kind(value: object, app_name: str, path: Path) -> AppKind:
    if value is None:
        return "app"
    if isinstance(value, str) and value in ("app", "misc"):
        return value
    raise ConfigError(f"app {app_name!r} has an invalid 'kind' in {path}")
