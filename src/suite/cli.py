from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from .completions import has_bash_completion, install_bash_completion
from .config import (
    Config,
    absolute_path,
    config_path,
    display_path,
    stored_path,
)
from .errors import SuiteError
from .git import check_app, get_remote_url
from .models import App, CheckResult
from .prompt_projects import add_projects, load_projects

CHECK_HEADERS = (
    "APP",
    "LOCAL DIR",
    "PRJ",
    "CMP",
    "TO COMMIT",
    "TO PUSH",
    "TO PULL",
    "DETAIL",
)


@dataclass
class AppContext:
    """Global options shared by every command."""

    color: str = "auto"
    config: Config | None = None


class _HelpOptions:
    """Give every command the same ``-h`` and ``--help`` options."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        context_settings = dict(kwargs.pop("context_settings", {}) or {})
        context_settings.setdefault("help_option_names", ["-h", "--help"])
        super().__init__(
            *args,
            context_settings=context_settings,  # ty: ignore[unknown-argument]
            **kwargs,
        )


class AppCommand(_HelpOptions, click.Command):
    """A leaf command with the app's standard help options."""


class AppGroup(_HelpOptions, click.Group):
    """A command group that propagates the standard command classes."""

    def command(  # ty: ignore[invalid-method-override]
        self,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Callable[[Callable[..., object]], click.Command] | click.Command:
        kwargs.setdefault("cls", AppCommand)
        return super().command(*args, **kwargs)

    def group(  # ty: ignore[invalid-method-override]
        self,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Callable[[Callable[..., object]], click.Group] | click.Group:
        kwargs.setdefault("cls", AppGroup)
        return super().group(*args, **kwargs)


@click.group(cls=AppGroup, invoke_without_command=True)
@click.version_option(package_name="suite-cli", prog_name="suite")
@click.option(
    "--completions",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=lambda ctx, param, value: _completions_callback(ctx, param, value),
    help="Write bash completions and exit.",
)
@click.option(
    "--config",
    "print_config",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=lambda ctx, param, value: _config_callback(ctx, param, value),
    help="Print the config file path and exit.",
)
@click.option(
    "--color",
    type=click.Choice(["auto", "always", "never"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Control colored output.",
)
@click.pass_context
def cli(ctx: click.Context, color: str) -> None:
    """Track the git status of every application in your suite."""
    ctx.obj = AppContext(color=color.lower())
    ctx.color = _resolve_force(ctx.obj.color)
    if ctx.invoked_subcommand is None:
        ctx.exit(_cmd_check(ctx, _load_config(ctx), []))


@cli.command(help="show changes to commit and commits to pull")
@click.argument("app", nargs=-1, help="only check these applications")
@click.option(
    "--no-fetch",
    is_flag=True,
    help="use cached remote state instead of running git fetch",
)
@click.option(
    "--update-dot-project",
    is_flag=True,
    help="add missing applications to ~/.prompt-projects",
)
@click.pass_context
def check(
    ctx: click.Context,
    app: tuple[str, ...],
    no_fetch: bool,
    update_dot_project: bool,
) -> None:
    """Show changes to commit and commits to pull."""
    ctx.exit(
        _cmd_check(
            ctx,
            _load_config(ctx),
            list(app),
            no_fetch=no_fetch,
            update_dot_project=update_dot_project,
        )
    )


@cli.command(help="add an application")
@click.argument("name", help="application name")
@click.argument(
    "path",
    type=click.Path(path_type=Path),
    help="local checkout (must be an existing directory)",
)
@click.option("-r", "--remote", help="override the checkout's git remote URL")
@click.option("--description", help="short description")
@click.option(
    "--misc",
    is_flag=True,
    help="mark a collection of apps and docs instead of a single app",
)
@click.pass_context
def add(
    ctx: click.Context,
    name: str,
    path: Path,
    remote: str | None,
    description: str | None,
    misc: bool,
) -> None:
    """Add an application to the database."""
    ctx.exit(
        _cmd_add(ctx, _load_config(ctx), name, path, remote, description, misc)
    )


@cli.command(help="remove an application")
@click.argument("name", help="application name")
@click.pass_context
def remove(ctx: click.Context, name: str) -> None:
    """Remove an application from the database."""
    ctx.exit(_cmd_remove(ctx, _load_config(ctx), name))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, returning an exit code instead of raising."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        with cli.make_context("suite", args) as ctx:
            cli.invoke(ctx)
        return 0
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except SuiteError as exc:
        _, err = _consoles(_color_mode_from_args(args))
        err.print(f"[red]error:[/red] {escape(str(exc))}", soft_wrap=True)
        return 2
    except (click.Abort, KeyboardInterrupt):
        return 1


def _completions_callback(
    ctx: click.Context,
    _param: click.Parameter,
    value: bool,
) -> None:
    if not value or ctx.resilient_parsing:
        return
    install_bash_completion(
        ctx.command,
        ctx.info_name or "suite",
        package_version("suite-cli"),
    )
    ctx.exit()


def _config_callback(
    ctx: click.Context,
    _param: click.Parameter,
    value: bool,
) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(config_path())
    ctx.exit()


def _load_config(ctx: click.Context) -> Config:
    if isinstance(ctx.obj, AppContext) and ctx.obj.config is not None:
        return ctx.obj.config
    config = Config.load()
    _, err = _consoles(_context_color(ctx))
    if config.created:
        err.print(
            f"[dim]Created config:[/dim] {escape(display_path(config.path))}"
        )
    for warning in config.warnings:
        err.print(
            f"[yellow]warning:[/yellow] {escape(warning)}",
            soft_wrap=True,
        )
    if isinstance(ctx.obj, AppContext):
        ctx.obj.config = config
    return config


def _context_color(ctx: click.Context) -> str:
    if isinstance(ctx.obj, AppContext):
        return ctx.obj.color
    return "auto"


def _resolve_force(mode: str) -> bool | None:
    """Resolve a color mode, honoring the environment for auto."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    force_color = os.environ.get("FORCE_COLOR")
    if force_color and force_color != "0":
        return True
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return None


def _consoles(mode: str) -> tuple[Console, Console]:
    force = _resolve_force(mode)
    options: dict[str, Any] = {}
    if force is True:
        options["force_terminal"] = True
    elif force is False:
        options["force_terminal"] = False
        options["no_color"] = True
    return Console(**options), Console(stderr=True, **options)


def _consoles_for(
    ctx: click.Context,
) -> tuple[Console, Console]:
    return _consoles(_context_color(ctx))


def _color_mode_from_args(args: Sequence[str]) -> str:
    for index, arg in enumerate(args):
        if arg == "--color" and index + 1 < len(args):
            return args[index + 1].lower()
        if arg.startswith("--color="):
            return arg.split("=", 1)[1].lower()
    return "auto"


def _stdout_is_tty() -> bool:
    """Report whether stdout is a terminal, where table chrome makes sense."""
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _cmd_check(
    ctx: click.Context,
    config: Config,
    names: list[str],
    *,
    no_fetch: bool = False,
    update_dot_project: bool = False,
) -> int:
    if names:
        known = {app.name for app in config.apps}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise SuiteError(f"unknown app(s): {', '.join(unknown)}")
        apps = [app for app in config.apps if app.name in names]
    else:
        apps = config.apps
    apps = sorted(apps, key=_app_sort_key)

    out, err = _consoles_for(ctx)
    tty = _stdout_is_tty()
    if not apps:
        message = "No apps configured. Add one with `suite add NAME PATH`."
        if tty:
            out.print(message)
        else:
            err.print(message)
        return 0

    projects = set(load_projects())
    missing = [app for app in apps if app.name not in projects]
    if update_dot_project and missing:
        added = add_projects(missing)
        projects.update(app.name for app in added)
        message = (
            f"Added {_plural(len(added), 'project')} to ~/.prompt-projects"
        )
        if tty:
            out.print(message)
        else:
            err.print(message)

    if tty:
        with out.status("Checking apps…", spinner="dots"):
            results = _check_all(apps, fetch=not no_fetch)
    else:
        results = _check_all(apps, fetch=not no_fetch)
    results.sort(key=lambda result: _app_sort_key(result.app))

    entries = [
        (
            result,
            result.app.name in projects,
            None
            if result.app.kind == "misc"
            else has_bash_completion(result.app.name),
        )
        for result in results
    ]
    rows = [
        _check_row(result, listed, has_completion)
        for result, listed, has_completion in entries
    ]
    headers, rows = _visible_rows(rows)

    if tty:
        out.print(
            _check_table(entries, rows, headers, out),
            soft_wrap=True,
            crop=False,
        )
    else:
        for row in rows:
            click.echo("\t".join(row))

    for result in results:
        if result.fetch_error:
            err.print(
                "[yellow]warning:[/yellow] "
                f"{escape(result.app.name)}: "
                f"{escape(result.fetch_error)}",
                soft_wrap=True,
            )

    return 1 if any(result.has_problem for result in results) else 0


def _check_all(apps: Sequence[App], *, fetch: bool) -> list[CheckResult]:
    """Check every application concurrently, preserving the input order."""
    if not apps:
        return []
    with ThreadPoolExecutor(max_workers=len(apps)) as pool:
        return list(pool.map(lambda app: check_app(app, fetch=fetch), apps))


def _visible_rows(
    rows: Sequence[tuple[str, ...]],
) -> tuple[tuple[str, ...], list[tuple[str, ...]]]:
    """Drop the DETAIL column when no row has anything to put in it."""
    if any(row[-1] for row in rows):
        return CHECK_HEADERS, list(rows)
    return CHECK_HEADERS[:-1], [row[:-1] for row in rows]


def _check_table(
    entries: Sequence[tuple[CheckResult, bool, bool | None]],
    rows: Sequence[Sequence[str]],
    headers: Sequence[str],
    console: Console,
) -> Table:
    table = Table(
        box=box.SIMPLE_HEAD,
        pad_edge=False,
        show_header=True,
        show_edge=False,
        header_style="bold",
        expand=False,
    )
    for header in headers:
        table.add_column(header, no_wrap=header == "DETAIL")
    for (result, listed, has_completion), row in zip(
        entries, rows, strict=True
    ):
        styles = _check_styles(result, listed, has_completion)[: len(headers)]
        table.add_row(
            *(
                Text(cell, style=style)
                for cell, style in zip(row, styles, strict=True)
            )
        )
    # Size the table from its contents and let long detail values overflow
    # the terminal instead of wrapping, matching how rows used to print.
    options = console.options.update_width(10_000)
    table.width = Measurement.get(console, options, table).maximum
    return table


def _check_row(
    result: CheckResult, listed: bool, has_completion: bool | None
) -> tuple[str, str, str, str, str, str, str, str]:
    name = result.app.name
    local_dir = display_path(result.app.local_dir)
    project = "✓" if listed else "x"
    completion = (
        "-" if has_completion is None else ("✓" if has_completion else "x")
    )
    if result.state == "missing":
        return (
            name,
            local_dir,
            project,
            completion,
            "-",
            "-",
            "-",
            f"missing: {display_path(result.app.local_dir)}",
        )
    if result.state == "not-git":
        message = result.message or "not a git repository"
        return (
            name,
            local_dir,
            project,
            completion,
            "-",
            "-",
            "-",
            f"{message}: {display_path(result.app.local_dir)}",
        )
    if result.state == "error":
        return (
            name,
            local_dir,
            project,
            completion,
            "-",
            "-",
            "-",
            f"error: {result.message or 'unknown error'}",
        )

    changes = (
        "clean" if result.changes == 0 else _plural(result.changes, "change")
    )
    if result.upstream is None:
        push = "-"
        pull = "no upstream"
    else:
        push = (
            "up to date"
            if result.ahead == 0
            else _plural(result.ahead, "commit")
        )
        pull = (
            "up to date"
            if result.behind == 0
            else _plural(result.behind, "commit")
        )

    detail = (
        "" if result.upstream is not None else result.branch or "detached HEAD"
    )
    return (name, local_dir, project, completion, changes, push, pull, detail)


def _check_styles(
    result: CheckResult, listed: bool, has_completion: bool | None
) -> tuple[str, str, str, str, str, str, str, str]:
    project = "green" if listed else "red"
    completion = (
        "dim"
        if has_completion is None
        else "green"
        if has_completion
        else "red"
    )
    if result.state != "ok":
        return (
            "bold red",
            "dim",
            project,
            completion,
            "dim",
            "dim",
            "dim",
            "red",
        )

    changes = "green" if result.changes == 0 else "yellow"
    if result.upstream is None:
        push = "dim"
        pull = "yellow"
    else:
        push = "green" if result.ahead == 0 else "yellow"
        pull = "green" if result.behind == 0 else "yellow"
    return (
        "bold",
        "dim",
        project,
        completion,
        changes,
        push,
        pull,
        "dim",
    )


def _app_sort_key(app: App) -> str:
    return app.name.casefold()


def _cmd_add(
    ctx: click.Context,
    config: Config,
    name: str,
    path: Path,
    remote: str | None,
    description: str | None,
    misc: bool,
) -> int:
    out, _ = _consoles_for(ctx)
    name = name.strip()
    if not name:
        raise SuiteError("application name cannot be empty")

    local_dir = absolute_path(path)
    if not local_dir.is_dir():
        raise SuiteError(
            f"path is not an existing directory: {display_path(local_dir)}"
        )

    remote = (remote or "").strip() or get_remote_url(local_dir)
    if remote is None:
        raise SuiteError(f"no git remote found for {display_path(local_dir)}")

    app = App(
        name=name,
        local_dir=local_dir,
        remote=remote,
        description=(description or "").strip() or None,
        kind="misc" if misc else "app",
    )
    existing = config.find(app.name)
    if existing is not None and not click.confirm(
        f"App {app.name!r} already exists. Overwrite?", default=False
    ):
        out.print(f"[yellow]Kept existing[/yellow] {escape(app.name)}.")
        return 0

    config.add_app(app, overwrite=existing is not None)
    config.save()

    action = "Updated" if existing is not None else "Added"
    out.print(
        f"{action} {escape(app.name)} -> {escape(stored_path(app.local_dir))}"
    )
    return 0


def _cmd_remove(ctx: click.Context, config: Config, name: str) -> int:
    out, _ = _consoles_for(ctx)
    app = config.remove_app(name.strip())
    config.save()
    out.print(
        f"Removed {escape(app.name)} ({escape(stored_path(app.local_dir))})"
    )
    return 0


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural if plural is not None else singular + 's'}"
