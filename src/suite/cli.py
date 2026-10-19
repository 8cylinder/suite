from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import Config, absolute_path, display_path
from .errors import SuiteError
from .git import check_app
from .models import App, CheckResult

DEFAULT_ORG_FILE = "suite.org"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="suite",
        description="Track the git status of every application in your suite.",
    )
    parser.add_argument("--version", action="version", version=f"suite {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    check = subparsers.add_parser("check", help="show changes to commit and commits to pull")
    check.add_argument("apps", nargs="*", metavar="APP", help="only check these applications")
    check.add_argument(
        "--no-fetch",
        action="store_true",
        help="use cached remote state instead of running git fetch",
    )

    subparsers.add_parser("list", help="list configured applications")

    add = subparsers.add_parser("add", help="add an application")
    add.add_argument("name", help="application name")
    add.add_argument(
        "-d", "--dir", dest="local_dir", type=Path, metavar="PATH", help="local checkout"
    )
    add.add_argument("-r", "--remote", help="git remote URL")
    add.add_argument("--description", help="short description")

    remove = subparsers.add_parser("remove", help="remove an application")
    remove.add_argument("name", help="application name")

    sync = subparsers.add_parser(
        "sync", help="add applications from an org file (default: ./suite.org)"
    )
    sync.add_argument("file", nargs="?", default=DEFAULT_ORG_FILE, metavar="FILE")

    config = subparsers.add_parser("config", help="show the config file location")
    config.add_argument("--show", action="store_true", help="also print the config file")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        config = Config.load()
        if config.created:
            print(f"Created config: {display_path(config.path)}", file=sys.stderr)

        if args.command == "check":
            return _cmd_check(config, args)
        if args.command == "list":
            return _cmd_list(config)
        if args.command == "add":
            return _cmd_add(config, args)
        if args.command == "remove":
            return _cmd_remove(config, args)
        if args.command == "sync":
            return _cmd_sync(config, args)
        if args.command == "config":
            return _cmd_config(config, args)
    except SuiteError as exc:
        print(f"suite: error: {exc}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_check(config: Config, args: argparse.Namespace) -> int:
    names: list[str] = args.apps
    if names:
        known = {app.name for app in config.apps}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise SuiteError(f"unknown app(s): {', '.join(unknown)}")
        apps = [app for app in config.apps if app.name in names]
    else:
        apps = config.apps

    if not apps:
        print("No apps configured. Add one with `suite add NAME --dir PATH`.")
        return 0

    results = [check_app(app, fetch=not args.no_fetch) for app in apps]
    _print_check_results(results)

    for result in results:
        if result.fetch_error:
            print(
                f"suite: warning: {result.app.name}: {result.fetch_error}",
                file=sys.stderr,
            )

    return 1 if any(result.has_problem for result in results) else 0


def _print_check_results(results: list[CheckResult]) -> None:
    rows = [_check_row(result) for result in results]
    _print_table(("APP", "TO COMMIT", "TO PULL", "DETAIL"), rows)

    commit_count = sum(1 for result in results if result.state == "ok" and result.changes > 0)
    pull_count = sum(1 for result in results if result.state == "ok" and result.behind > 0)
    problem_count = sum(1 for result in results if result.has_problem)

    parts: list[str] = []
    if commit_count:
        parts.append(f"{commit_count} with changes to commit")
    if pull_count:
        parts.append(f"{pull_count} with commits to pull")
    if problem_count:
        parts.append(f"{problem_count} with problems")
    summary = ", ".join(parts) if parts else "nothing to do"
    print()
    print(f"{_plural(len(results), 'app')}: {summary}.")


def _check_row(result: CheckResult) -> tuple[str, str, str, str]:
    name = result.app.name
    if result.state == "missing":
        return (name, "-", "-", f"missing: {display_path(result.app.local_dir)}")
    if result.state == "not-git":
        message = result.message or "not a git repository"
        return (name, "-", "-", f"{message}: {display_path(result.app.local_dir)}")
    if result.state == "error":
        return (name, "-", "-", f"error: {result.message or 'unknown error'}")

    changes = "clean" if result.changes == 0 else _plural(result.changes, "change")
    if result.upstream is None:
        pull = "no upstream"
    elif result.behind == 0:
        pull = "up to date"
    else:
        pull = _plural(result.behind, "commit")

    detail = result.upstream or result.branch or "detached HEAD"
    if result.ahead:
        detail = f"{detail} ({result.ahead} ahead)"
    return (name, changes, pull, detail)


def _cmd_list(config: Config) -> int:
    if not config.apps:
        print("No apps configured. Add one with `suite add NAME --dir PATH`.")
    else:
        rows = [(app.name, display_path(app.local_dir), app.remote or "-") for app in config.apps]
        _print_table(("NAME", "LOCAL DIR", "REMOTE"), rows)
    print()
    print(f"Config: {display_path(config.path)} ({_plural(len(config.apps), 'app')})")
    return 0


def _cmd_add(config: Config, args: argparse.Namespace) -> int:
    name = args.name.strip()
    if not name:
        raise SuiteError("application name cannot be empty")

    local_dir = (
        absolute_path(args.local_dir)
        if args.local_dir is not None
        else absolute_path(config.apps_root / name)
    )
    app = App(
        name=name,
        local_dir=local_dir,
        remote=(args.remote or "").strip() or None,
        description=(args.description or "").strip() or None,
    )
    config.add_app(app)
    config.save()

    print(f"Added {app.name} -> {display_path(app.local_dir)}")
    if not app.local_dir.is_dir():
        print(
            f"suite: warning: {display_path(app.local_dir)} does not exist yet",
            file=sys.stderr,
        )
    return 0


def _cmd_remove(config: Config, args: argparse.Namespace) -> int:
    app = config.remove_app(args.name.strip())
    config.save()
    print(f"Removed {app.name} ({display_path(app.local_dir)})")
    return 0


def _cmd_sync(config: Config, args: argparse.Namespace) -> int:
    org_file = absolute_path(Path(args.file))
    if not org_file.is_file():
        raise SuiteError(f"org file not found: {org_file}")

    stats = config.sync_from_org(org_file)
    if stats.added or stats.updated:
        config.save()

    changes: list[str] = []
    if stats.added:
        changes.append(f"{len(stats.added)} added")
    if stats.updated:
        changes.append(f"{len(stats.updated)} updated")
    summary = ", ".join(changes) if changes else "no changes"
    print(f"Synced {display_path(org_file)}: {summary}.")
    return 0


def _cmd_config(config: Config, args: argparse.Namespace) -> int:
    print(display_path(config.path))
    if args.show:
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
        line = "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        print(line.rstrip())


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural if plural is not None else singular + 's'}"
