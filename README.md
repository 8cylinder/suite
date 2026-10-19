# suite

`suite` keeps a local database of your applications and checks each one for
uncommitted changes and commits waiting to be pulled.

The database is a YAML file seeded from [`suite.org`](./suite.org) on first run.
Each entry stores the application name, local checkout, remote, and description.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- git

## Install

```sh
uv sync
uv run suite check
```

To make `suite` available as a standalone command:

```sh
uv tool install .
```

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
`local_dir` in the config file (or use `suite add --dir`) if your repositories
live somewhere else.

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

## Commands

| Command | Description |
| --- | --- |
| `suite check [APP ...]` | Scan applications for uncommitted changes and commits to pull. |
| `suite list` | List configured applications and their local directories. |
| `suite add NAME [--dir PATH] [--remote URL]` | Add an application to the database. |
| `suite remove NAME` | Remove an application from the database. |
| `suite sync [FILE]` | Add new applications from `suite.org` and refresh their metadata. |
| `suite config [--show]` | Print the config path, optionally with the file contents. |

### What `check` does

For every application, `suite check`:

1. Verifies the local directory exists and is a git working tree.
2. Runs `git fetch --all` so remote state is current (disable with `--no-fetch`).
3. Counts uncommitted, staged, and untracked files as **changes to commit**.
4. Compares `HEAD` with its upstream branch to count **commits to pull**.

```text
APP       TO COMMIT  TO PULL     DETAIL
cm        2 changes  3 commits   origin/main (1 ahead)
tether    clean      up to date  origin/main
prism     -          -           missing: ~/dev/prism

3 apps: 1 with changes to commit, 1 with commits to pull, 1 with problems.
```

`check` exits with `0` when every app was inspected successfully, and `1` when
an app is missing, is not a git repository, or cannot be inspected. Uncommitted
changes and commits to pull do not affect the exit code.

If a fetch fails, `suite` shows a warning and still reports the state it can
read from the cached remote-tracking branch.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```
