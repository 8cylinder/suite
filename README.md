# suite

`suite` keeps a local database of your applications and checks each one for
uncommitted changes, commits waiting to be pulled, and installed bash
completions.

Repository: <https://github.com/8cylinder/suite>

## Requirements

- Python 3.11 or newer.
- [uv](https://docs.astral.sh/uv/).
- make and git.
- bash >= 4.4 for the completion script.
- bash-completion >= 2.18 for automatic completion loading.
- gitleaks >= 8.19 to commit; see the
  [gitleaks install instructions](https://github.com/gitleaks/gitleaks#installing).

`suite` is supported on Linux and macOS. The completion script is bash-only;
zsh and fish are not supported.

## Installation

Clone the repository and install from source:

```sh
git clone https://github.com/8cylinder/suite.git
cd suite
make sync
make install
```

`make install` installs the `suite` command, writes the bash completion
script, and installs the man page. To install only the command, run
`uv tool install --editable --force .`.

## Quick start

Add an application whose checkout already exists:

```sh
suite add cm ~/dev/cm
```

Check every application:

```sh
suite check
```

Check only the applications you name:

```sh
suite check cm tether
```

## Command reference

| Command | Description |
| --- | --- |
| `suite check [APP ...] [--no-fetch] [--update-dot-project]` | Check applications for uncommitted changes, commits to pull, installed completions, and prompt-project registration. |
| `suite` | Check every application; same as `suite check`. |
| `suite add NAME PATH [-r/--remote URL] [--description TEXT] [--misc]` | Add an application whose checkout already exists at `PATH`. |
| `suite remove NAME` | Remove an application from the database. |
| `suite -h`, `suite --help` | Show help for `suite` or a subcommand. |

Run `suite --help` or `man suite` for the complete option list.

### Global options

| Option | Description |
| --- | --- |
| `-h`, `--help` | Show help for `suite` or a subcommand. |
| `--version` | Print the installed version. |
| `--config` | Print the absolute config file path and exit without creating it. |
| `--completions` | Write the bash completion script and exit. |
| `--color [auto\|always\|never]` | Control colored output. Defaults to `auto`. |

`--config`, `--completions`, `--color`, `--version`, and `--help` are root
options and must appear before a subcommand.

With `--color=auto`, `NO_COLOR` disables color and `FORCE_COLOR` forces it.
`TERM=dumb` also disables color for `auto`. `--color=always` and
`--color=never` take precedence over the environment.

### `check`

```text
suite check [APP ...] [--no-fetch] [--update-dot-project]
```

- `APP ...`: check only these applications. Unknown names are an error.
- `--no-fetch`: use cached remote state instead of running `git fetch`.
- `--update-dot-project`: add missing applications to `~/.prompt-projects`
  before printing the table.

Running `suite` without a command is the same as `suite check`.

Applications are checked in parallel, one thread per application, then printed
once every check has finished, in alphabetical order by name. On a terminal a
spinner is shown while the checks run. When stdout is not a terminal, the
header is omitted and the remaining columns are separated by a single tab, so
each application is one line of tab-separated fields (for example
`suite check | sort`, or `suite check | cut -f1,5-8`). When no row has a detail
value, the DETAIL field is omitted and each line has seven fields instead of
eight.

For every application, `suite check`:

1. Verifies the local directory exists and is a git working tree.
2. Runs `git fetch --all` so remote state is current (disable with
   `--no-fetch`).
3. Counts uncommitted, staged, and untracked files as **changes to commit**.
4. Compares `HEAD` with its upstream branch to count **commits to pull** and
   **commits to push**.
5. Checks whether the app has a bash completion script installed.
6. Checks whether the application is registered in `~/.prompt-projects`.

The **LOCAL DIR** column shows the absolute path to the application's local
checkout.

The **PRJ** column shows `✓` when the application is registered by name and
`x` when it is missing. Pass `--update-dot-project` to append missing
applications to `~/.prompt-projects` before the table is printed.

The **CMP** column shows `✓` when the application's completion script is
installed at `~/.local/share/bash-completion/completions/APP.bash` (or
`$XDG_DATA_HOME/bash-completion/completions/APP.bash` when `XDG_DATA_HOME` is
set), and `x` when it is missing. Install completions with
`APP --completions`. Misc entries show a dim `-` because completions do not
apply to them. A missing script is informational: it does not affect `check`'s
exit code.

The **DETAIL** column stays blank for applications that track an upstream
branch. It shows the local branch when there is no upstream, `detached HEAD`
when the checkout is detached, and the reason an application is missing, is
not a git repository, or could not be inspected. When every row is blank the
column is omitted entirely.

The table is colorized with [Rich](https://github.com/Textualize/rich): green
for clean or up-to-date values, yellow for changes or commits to pull/push,
red for unregistered projects, missing completions, and application problems,
and dim for neutral details. Colors are disabled automatically when output is
not a terminal, along with the header.

```text
APP     LOCAL DIR             PRJ  CMP  TO COMMIT    TO PUSH      TO PULL      DETAIL
cm      /home/user/dev/cm     x    ✓    2 changes    1 commit     3 commits
tether  /home/user/dev/tether ✓    x    clean        up to date   up to date
prism   /home/user/dev/prism  ✓    x    -            -            -             missing: /home/user/dev/prism
bin     /home/user/bin        x    -    clean        up to date   up to date
```

### `add`

```text
suite add NAME PATH [-r/--remote URL] [--description TEXT] [--misc]
```

`PATH` must point at an existing directory. `add` saves the checkout's git
remote (preferring `origin`) to the config; use `--remote` to override the
detected URL. If the checkout has no remote, `suite add` fails.

Use `--misc` for a directory such as `~/bin` that holds a collection of small
apps and docs rather than a single application. Misc entries are stored with
`kind = "misc"` and are not checked for bash completions.

If `NAME` is already configured, `add` asks before overwriting the existing
record. Confirming replaces the stored local directory, remote, description,
and misc flag; declining leaves the record unchanged.

### `remove`

```text
suite remove NAME
```

Removes an application from the database. It does not delete the checkout.

### Exit codes

- `0`: success. `check` also exits `0` when every app was inspected
  successfully, even if there are uncommitted changes or commits to pull/push.
- `1`: `check` found an app that is missing, is not a git repository, or cannot
  be inspected. Ctrl-C also exits `1` without a traceback.
- `2`: a configuration, usage, or command error.

If a fetch fails, `suite` shows a warning and still reports the state it can
read from the cached remote-tracking branch.

## Configuration

The configuration is a TOML file in the platform config directory. Print the
exact path with:

```sh
suite --config
```

| Platform | Default path |
| --- | --- |
| Linux | `~/.config/suite/config.toml` |
| macOS | `~/Library/Application Support/suite/config.toml` |
| Windows | `%LOCALAPPDATA%\suite\config.toml` |

The first command that needs the database creates an empty config file with
mode `0600`. A missing file is not an error. An existing `config.yaml` from an
older release is migrated automatically the first time `suite` runs; the old
file is left in place.

```toml
# ~/.config/suite/config.toml
apps_root = "~/dev"

[[apps]]
name = "cm"
local_dir = "~/dev/cm"
remote = "git@github.com:8cylinder/commit.git"
description = "Generate a git commit message from the working-tree diff."

[[apps]]
name = "tether"
local_dir = "~/dev/tether"
remote = "git@github.com:8cylinder/tether.git"

[[apps]]
name = "bin"
local_dir = "~/bin"
kind = "misc"
```

Paths may be absolute or start with `~` or an environment variable such as
`$HOME` or `${HOME}`. Relative paths are resolved against the config file's
directory. `suite check` always prints absolute paths, while `suite add`
stores paths under the home directory with `~` and all other paths as absolute
paths.

Precedence is command-line option, then the config value, then the code
default. Invalid TOML names the file and exits nonzero; unknown keys produce a
warning on stderr and are ignored.

## Bash completions

```sh
suite --completions
```

The command writes a static script named `suite.bash` and prints only its
absolute path to stdout. The source command and any warnings go to stderr:

```console
$ suite --completions
/home/user/.local/share/bash-completion/completions/suite.bash
To use it in this shell:
  source /home/user/.local/share/bash-completion/completions/suite.bash
```

Resolve the destination in this order:

1. The first non-empty `BASH_COMPLETION_USER_DIR` entry.
2. `XDG_DATA_HOME` when set.
3. `~/.local/share`.

The script requires bash >= 4.4. Automatic loading requires bash-completion
>= 2.18, which prefers the `.bash` suffix. On macOS, `/bin/bash` is 3.2 and the
default login shell is zsh; install a newer bash (for example
`brew install bash`) and source the script from bash. zsh is not supported.

## Man page

```sh
man suite
```

`make install` builds and installs the page to
`${XDG_DATA_HOME:-$HOME/.local/share}/man/man1/suite.1`. If `man suite` cannot
find it, add that directory to `MANPATH`. Installing the package with
`uv tool install` alone installs the command but not the man page.

Build the page without installing it with `make man`; the output is
`docs/_build/man/suite.1`.

## Development

```sh
make sync    # install dependencies
make hooks   # install the git hook that blocks secrets
make fmt     # format with ruff
make lint    # lint and autofix with ruff
make type    # type-check with ty
make test    # run pytest with coverage
make check   # format check, lint, type check, tests, and man page
make build   # build the wheel and sdist into dist/
```

`make hooks` sets `core.hooksPath` to `.githooks`; run it once per clone. The
hook refuses commits when gitleaks is missing or older than 8.19. Commit with
`git commit --no-verify` to bypass it. CI runs `make secrets`, so a bypassed
secret is still caught before it reaches the default branch.

`make secrets` scans the repository history with gitleaks and needs `gitleaks`
on `PATH`.

Run one test with:

```sh
uv run pytest tests/test_cli.py::test_first_run_creates_config
```

## License

`suite` is licensed under GPL-2.0-only. See [LICENSE](LICENSE).

Copyright (C) 2026 Sheldon McGrandle.

## Contributing and issues

Report bugs and request features at
<https://github.com/8cylinder/suite/issues>. The repository is at
<https://github.com/8cylinder/suite>.
