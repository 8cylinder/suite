from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

import click
from click.shell_completion import shell_complete
from rich.console import Console
from rich.text import Text

from . import __version__
from .completions import has_bash_completion, install_bash_completion
from .config import Config, absolute_path, display_path
from .errors import SuiteError
from .git import check_app, get_remote_url
from .models import App, CheckResult
from .prompt_projects import add_projects, load_projects

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

CHECK_HEADERS = ("APP", "PRJ", "CMP", "TO COMMIT", "TO PUSH", "TO PULL", "DETAIL")
# Rows are printed as each app finishes, so status columns cannot be sized from
# the full table. Size them for the longest static label and let unusually long
# values push the detail column right.
PROJECT_COLUMN_WIDTH = max(len(CHECK_HEADERS[1]), len("x"))
COMPLETION_COLUMN_WIDTH = max(len(CHECK_HEADERS[2]), len("x"))
STATUS_COLUMN_WIDTH = max(len(CHECK_HEADERS[3]), len("no upstream"))


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
        ctx.exit(_cmd_list(_load_config()))


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


@cli.command("list", context_settings=CONTEXT_SETTINGS, help="list configured applications")
@click.pass_context
def list_apps(ctx: click.Context) -> None:
    ctx.exit(_cmd_list(_load_config()))


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
    widths = _check_column_widths(apps)
    if tty:
        console.print(
            _format_check_row(CHECK_HEADERS, widths, ("bold",) * len(CHECK_HEADERS)),
            soft_wrap=True,
        )

    results: list[CheckResult] = []
    for app in apps:
        result = check_app(app, fetch=not no_fetch)
        results.append(result)
        listed = app.name in projects
        has_completion = None if app.kind == "misc" else has_bash_completion(app.name)
        row = _check_row(result, listed, has_completion)
        if tty:
            console.print(
                _format_check_row(row, widths, _check_styles(result, listed, has_completion)),
                soft_wrap=True,
            )
        else:
            print("\t".join(row))
        if result.fetch_error:
            print(
                f"suite: warning: {result.app.name}: {result.fetch_error}",
                file=sys.stderr,
            )

    if tty:
        _print_check_summary(results)
    return 1 if any(result.has_problem for result in results) else 0


def _check_column_widths(apps: Sequence[App]) -> tuple[int, int, int, int, int, int, int]:
    name_width = max(len(CHECK_HEADERS[0]), *(len(app.name) for app in apps))
    return (
        name_width,
        PROJECT_COLUMN_WIDTH,
        COMPLETION_COLUMN_WIDTH,
        STATUS_COLUMN_WIDTH,
        STATUS_COLUMN_WIDTH,
        STATUS_COLUMN_WIDTH,
        0,
    )


def _print_check_summary(results: list[CheckResult]) -> None:
    commit_count = sum(1 for result in results if result.state == "ok" and result.changes > 0)
    pull_count = sum(1 for result in results if result.state == "ok" and result.behind > 0)
    push_count = sum(1 for result in results if result.state == "ok" and result.ahead > 0)
    problem_count = sum(1 for result in results if result.has_problem)

    parts: list[str] = []
    if commit_count:
        parts.append(f"{commit_count} with changes to commit")
    if pull_count:
        parts.append(f"{pull_count} with commits to pull")
    if push_count:
        parts.append(f"{push_count} with commits to push")
    if problem_count:
        parts.append(f"{problem_count} with problems")
    summary = ", ".join(parts) if parts else "nothing to do"
    print()
    print(f"{_plural(len(results), 'app')}: {summary}.")


def _check_row(
    result: CheckResult, listed: bool, has_completion: bool | None
) -> tuple[str, str, str, str, str, str, str]:
    name = result.app.name
    project = "✓" if listed else "x"
    completion = "-" if has_completion is None else ("✓" if has_completion else "x")
    if result.state == "missing":
        return (
            name,
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

    detail = result.upstream or result.branch or "detached HEAD"
    return (name, project, completion, changes, push, pull, detail)


def _check_styles(
    result: CheckResult, listed: bool, has_completion: bool | None
) -> tuple[str, str, str, str, str, str, str]:
    project = "green" if listed else "red"
    completion = "dim" if has_completion is None else "green" if has_completion else "red"
    if result.state != "ok":
        return ("bold red", project, completion, "dim", "dim", "dim", "red")

    changes = "green" if result.changes == 0 else "yellow"
    if result.upstream is None:
        push = "dim"
        pull = "yellow"
    else:
        push = "green" if result.ahead == 0 else "yellow"
        pull = "green" if result.behind == 0 else "yellow"
    return ("bold", project, completion, changes, push, pull, "dim")


def _format_check_row(row: Sequence[str], widths: Sequence[int], styles: Sequence[str]) -> Text:
    text = Text()
    for index, (cell, width, style) in enumerate(zip(row, widths, styles, strict=True)):
        if index:
            text.append("  ")
        text.append(cell, style=style)
        text.append(" " * (width - len(cell)))
    return text


def _app_sort_key(app: App) -> str:
    return app.name.casefold()


def _cmd_list(config: Config) -> int:
    tty = _stdout_is_tty()
    if not config.apps:
        print(
            "No apps configured. Add one with `suite add NAME PATH`.",
            file=sys.stdout if tty else sys.stderr,
        )
    else:
        rows = [
            (app.name, display_path(app.local_dir), app.remote or "-")
            for app in sorted(config.apps, key=_app_sort_key)
        ]
        if tty:
            _print_table(("NAME", "LOCAL DIR", "REMOTE"), rows)
        else:
            for row in rows:
                print("\t".join(row))
    if tty:
        print()
        print(f"Config: {display_path(config.path)} ({_plural(len(config.apps), 'app')})")
    return 0


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
    print(f"{action} {app.name} -> {display_path(app.local_dir)}")
    return 0


def _cmd_remove(config: Config, name: str) -> int:
    app = config.remove_app(name.strip())
    config.save()
    print(f"Removed {app.name} ({display_path(app.local_dir)})")
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


def _print_table(headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> None:
    widths = [max(len(row[index]) for row in (headers, *rows)) for index in range(len(headers))]
    for row in (headers, *rows):
        print(_format_row(row, widths))


def _format_row(row: Sequence[str], widths: Sequence[int]) -> str:
    line = "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
    return line.rstrip()


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural if plural is not None else singular + 's'}"
