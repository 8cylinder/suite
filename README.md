# suite

`suite` keeps a local database of your applications and checks each one for
uncommitted changes and commits waiting to be pulled.

Repository: <https://github.com/8cylinder/suite>

The database is a YAML file seeded from [`suite.org`](./suite.org) on first run.
Each entry stores the application name, local checkout, remote, and description.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- make
- git

## Install

Clone the repository and build the environment:

```sh
git clone https://github.com/8cylinder/suite.git
cd suite
make sync
```

Run it from the checkout:

```sh
uv run suite check
```

To make `suite` available as a standalone command:

```sh
make install
```

`make install` runs `uv tool install --editable --force .`.

## First run

Running any `suite` command creates `config.yaml` in the platform config
directory:

| Platform | Default location |
| --- | --- |
| Linux | `~/.config/suite/config.yaml` |
| macOS | `~/Library/Application Support/suite/config.yaml` |
| Windows | `%LOCALAPPDATA%\suite\config.yaml` |

Use `suite config` to print the exact path and `suite config --show` to print
the file. Set `SUITE_CONFIG=/path/to/config.yaml` to use a different file.

On first run, `suite` reads `suite.org` from the current directory and seeds the
database. It looks for each checkout next to `suite.org` first, then falls back
to `~/dev/<name>`. Existing entries are never moved by `suite sync`, so edit
`local_dir` in the config file (or use `suite add NAME PATH`) if your
repositories live somewhere else.

```yaml
# suite configuration
# Edit local_dir values to point at each application's checkout.
apps_root: ~/dev
apps:
  - name: cm
    local_dir: ~/dev/cm
    remote: git@github.com:8cylinder/commit.git
    description: Generate a git commit message from the working-tree diff.
  - name: tether
    local_dir: ~/dev/tether
    remote: git@github.com:8cylinder/tether.git
```

## Global options

| Option | Description |
| --- | --- |
| `-h`, `--help` | Show help for `suite` or a subcommand. |
| `--version` | Print `suite`'s version. |
| `--completions` | Install the bash completion script and exit. |

`suite --completions` writes the script to
`~/.local/share/bash-completion/completions/suite` (or
`$XDG_DATA_HOME/bash-completion/completions/suite` when `XDG_DATA_HOME` is
set), prints the path, and prints the command to source it in the current
terminal. The generated script invokes `suite` from `PATH`, so run `make
install` first if you normally use `uv run suite`.

## Commands

| Command | Description |
| --- | --- |
| `suite check [APP ...] [--no-fetch] [--update-dot-project]` | Scan applications for uncommitted changes, commits to pull, and prompt project registration. |
| `suite` | List configured applications and their local directories (same as `suite list`). |
| `suite list` | List configured applications and their local directories. |
| `suite add NAME PATH [--remote URL] [--description TEXT]` | Add an application whose checkout already exists at `PATH`. |
| `suite remove NAME` | Remove an application from the database. |
| `suite sync [FILE]` | Add new applications from `suite.org` and refresh their metadata. |
| `suite config [--show]` | Print the config path, optionally with the file contents. |

### `check`

```text
suite check [APP ...] [--no-fetch] [--update-dot-project]
```

- `APP ...`: check only these applications. Unknown names are an error.
- `--no-fetch`: use cached remote state instead of running `git fetch`.
- `--update-dot-project`: add missing applications to `~/.prompt-projects`
  before printing the table.

Applications are checked and printed in alphabetical order by name.

### `list`

```text
suite list
```

Prints the configured application name, local directory, and remote in
alphabetical order by name. Running `suite` without a command does the same.

### `add`

```text
suite add NAME PATH [-r/--remote URL] [--description TEXT]
```

`PATH` must point at an existing directory. `add` saves the checkout's git
remote (preferring `origin`) to the config; use `--remote` to override the
detected URL. If the checkout has no remote, `suite add` fails. To add an
application from `suite.org`, use `suite sync` instead.

### `remove`

```text
suite remove NAME
```

Removes an application from the database. It does not delete the checkout.

### `sync`

```text
suite sync [FILE]
```

Reads the given org file (default: `./suite.org`), adds applications that are
not configured yet, and refreshes remote and description metadata for existing
applications. Existing `local_dir` values are preserved.

### `config`

```text
suite config [--show]
```

Prints the config file path. With `--show`, also prints the YAML contents.

### What `check` does

For every application, `suite check`:

1. Verifies the local directory exists and is a git working tree.
2. Runs `git fetch --all` so remote state is current (disable with `--no-fetch`).
3. Counts uncommitted, staged, and untracked files as **changes to commit**.
4. Compares `HEAD` with its upstream branch to count **commits to pull** and
   **commits to push**.
5. Checks whether the application is registered in `~/.prompt-projects`.

The **PRJ** column shows `✓` when the application is registered by name and `x`
when it is missing. Pass `--update-dot-project` to append missing applications
to `~/.prompt-projects` before the table is printed.

The table is colorized with [Rich](https://github.com/Textualize/rich): green for
clean or up-to-date values, yellow for changes or commits to pull/push, red for
unregistered projects and application problems, and dim for neutral details.
Colors are disabled automatically when output is not a terminal.

```text
APP     PRJ  TO COMMIT    TO PUSH      TO PULL      DETAIL
cm      x    2 changes    1 commit     3 commits    origin/main
tether  ✓    clean        up to date   up to date    origin/main
prism   ✓    -            -            -             missing: ~/dev/prism

3 apps: 1 with changes to commit, 1 with commits to pull,
1 with commits to push, 1 with problems.
```

### Exit codes

- `0`: success. `check` also exits `0` when every app was inspected
  successfully, even if there are uncommitted changes or commits to pull/push.
- `1`: `check` found an app that is missing, is not a git repository, or cannot
  be inspected. Ctrl-C also exits `1` without a traceback.
- `2`: a configuration, usage, or command error.

If a fetch fails, `suite` shows a warning and still reports the state it can
read from the cached remote-tracking branch.

## Development

```sh
make sync    # install dependencies
make fmt     # format with ruff
make lint    # lint and autofix with ruff
make type    # type-check with ty
make test    # run pytest
make check   # run format check, lint, type check, and tests
```
