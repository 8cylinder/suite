from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click
from click.shell_completion import shell_complete
from rich import box
from rich.console import Console
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from . import __version__
from .completions import has_bash_completion, install_bash_completion
from .config import Config, absolute_path, display_path, stored_path
from .errors import SuiteError
from .git import check_app, get_remote_url
from .models import App, CheckResult
from .prompt_projects import add_projects, load_projects

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

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


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(__version__, prog_name="suite", message="suite %(version)s")
@click.option("--completions", is_flag=True, help="install the bash completion script and exit")
@click.pass_context
def cli(ctx: click.Context, completions: bool) -> None:
    """Track the git status of every application in your suite."""
    if completions:
        path = install_bash_completion()
        click.echo(f"Completion script: {display_path(path)}")
        click.echo(f"Source it now: source {display_path(path)}")
        ctx.exit(0)
    if ctx.invoked_subcommand is None:
        ctx.exit(_cmd_check(_load_config(), []))


@cli.command(context_settings=CONTEXT_SETTINGS, help="show changes to commit and commits to pull")
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
    config = _load_config()
    ctx.exit(
        _cmd_check(config, list(app), no_fetch=no_fetch, update_dot_project=update_dot_project)
    )


@cli.command(context_settings=CONTEXT_SETTINGS, help="add an application")
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
    ctx.exit(_cmd_add(_load_config(), name, path, remote, description, misc))


@cli.command(context_settings=CONTEXT_SETTINGS, help="remove an application")
@click.argument("name", help="application name")
@click.pass_context
def remove(ctx: click.Context, name: str) -> None:
    ctx.exit(_cmd_remove(_load_config(), name))


@cli.command(context_settings=CONTEXT_SETTINGS, help="show the config file location")
@click.option("--show", is_flag=True, help="also print the config file")
@click.pass_context
def config(ctx: click.Context, show: bool) -> None:
    ctx.exit(_cmd_config(_load_config(), show))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, returning an exit code instead of raising."""
    args = list(sys.argv[1:] if argv is None else argv)
    complete_var = "_SUITE_COMPLETE"
    instruction = os.environ.get(complete_var)
    if instruction is not None:
        return shell_complete(cli, {}, "suite", complete_var, instruction)
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
        click.echo(f"suite: error: {exc}", err=True)
        return 2
    except (click.Abort, KeyboardInterrupt):
        return 1


def _load_config() -> Config:
    config = Config.load()
    if config.created:
        click.echo(f"Created config: {display_path(config.path)}", err=True)
    return config


def _stdout_is_tty() -> bool:
    """Report whether stdout is a terminal, where table chrome makes sense."""
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _cmd_check(
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

    tty = _stdout_is_tty()
    if not apps:
        print(
            "No apps configured. Add one with `suite add NAME PATH`.",
            file=sys.stdout if tty else sys.stderr,
        )
        return 0

    projects = set(load_projects())
    missing = [app for app in apps if app.name not in projects]
    if update_dot_project and missing:
        added = add_projects(missing)
        projects.update(app.name for app in added)
        print(
            f"Added {_plural(len(added), 'project')} to ~/.prompt-projects",
            file=sys.stdout if tty else sys.stderr,
        )

    console = Console()
    if tty:
        with console.status("Checking apps…", spinner="dots"):
            results = _check_all(apps, fetch=not no_fetch)
    else:
        results = _check_all(apps, fetch=not no_fetch)
    results.sort(key=lambda result: _app_sort_key(result.app))

    entries = [
        (
            result,
            result.app.name in projects,
            None if result.app.kind == "misc" else has_bash_completion(result.app.name),
        )
        for result in results
    ]
    rows = [
        _check_row(result, listed, has_completion) for result, listed, has_completion in entries
    ]
    headers, rows = _visible_rows(rows)

    if tty:
        console.print(_check_table(entries, rows, headers, console), soft_wrap=True, crop=False)
    else:
        for row in rows:
            print("\t".join(row))

    for result in results:
        if result.fetch_error:
            print(
                f"suite: warning: {result.app.name}: {result.fetch_error}",
                file=sys.stderr,
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
    for (result, listed, has_completion), row in zip(entries, rows, strict=True):
        styles = _check_styles(result, listed, has_completion)[: len(headers)]
        table.add_row(*(Text(cell, style=style) for cell, style in zip(row, styles, strict=True)))
    # Size the table from its contents and let long detail values overflow the
    # terminal instead of wrapping, matching how the rows used to be printed.
    options = console.options.update_width(10_000)
    table.width = Measurement.get(console, options, table).maximum
    return table


def _check_row(
    result: CheckResult, listed: bool, has_completion: bool | None
) -> tuple[str, str, str, str, str, str, str, str]:
    name = result.app.name
    local_dir = display_path(result.app.local_dir)
    project = "✓" if listed else "x"
    completion = "-" if has_completion is None else ("✓" if has_completion else "x")
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

    changes = "clean" if result.changes == 0 else _plural(result.changes, "change")
    if result.upstream is None:
        push = "-"
        pull = "no upstream"
    else:
        push = "up to date" if result.ahead == 0 else _plural(result.ahead, "commit")
        pull = "up to date" if result.behind == 0 else _plural(result.behind, "commit")

    detail = "" if result.upstream is not None else result.branch or "detached HEAD"
    return (name, local_dir, project, completion, changes, push, pull, detail)


def _check_styles(
    result: CheckResult, listed: bool, has_completion: bool | None
) -> tuple[str, str, str, str, str, str, str, str]:
    project = "green" if listed else "red"
    completion = "dim" if has_completion is None else "green" if has_completion else "red"
    if result.state != "ok":
        return ("bold red", "dim", project, completion, "dim", "dim", "dim", "red")

    changes = "green" if result.changes == 0 else "yellow"
    if result.upstream is None:
        push = "dim"
        pull = "yellow"
    else:
        push = "green" if result.ahead == 0 else "yellow"
        pull = "green" if result.behind == 0 else "yellow"
    return ("bold", "dim", project, completion, changes, push, pull, "dim")


def _app_sort_key(app: App) -> str:
    return app.name.casefold()


def _cmd_add(
    config: Config,
    name: str,
    path: Path,
    remote: str | None,
    description: str | None,
    misc: bool,
) -> int:
    name = name.strip()
    if not name:
        raise SuiteError("application name cannot be empty")

    local_dir = absolute_path(path)
    if not local_dir.is_dir():
        raise SuiteError(f"path is not an existing directory: {display_path(local_dir)}")

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
        print(f"Kept existing {app.name}.")
        return 0

    config.add_app(app, overwrite=existing is not None)
    config.save()

    action = "Updated" if existing is not None else "Added"
    print(f"{action} {app.name} -> {stored_path(app.local_dir)}")
    return 0


def _cmd_remove(config: Config, name: str) -> int:
    app = config.remove_app(name.strip())
    config.save()
    print(f"Removed {app.name} ({stored_path(app.local_dir)})")
    return 0


def _cmd_config(config: Config, show: bool) -> int:
    print(display_path(config.path))
    if show:
        try:
            text = config.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SuiteError(f"could not read {config.path}: {exc}") from exc
        print()
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural if plural is not None else singular + 's'}"
