# suite

## SYNOPSIS

`suite [OPTIONS] [COMMAND] [ARGS]...`

## DESCRIPTION

`suite` keeps a local TOML database of your applications and checks each
application for uncommitted changes, commits waiting to be pulled, and
installed bash completions.

Running `suite` without a command is the same as `suite check`.

## OPTIONS

`-h`, `--help`
: Show help for `suite` or a subcommand.

`--version`
: Print the installed version.

`--config`
: Print the absolute path to the configuration file and exit.

`--completions`
: Write the bash completion script and exit.

`--color [auto|always|never]`
: Control colored output. The default is `auto`.

## COMMANDS

```{click} suite.cli:cli
:prog: suite
:nested: full
```

## FILES

`~/.config/suite/config.toml`
: The configuration file on Linux. The exact path follows the platform
  configuration directory and can be printed with `suite --config`.

`~/.local/share/bash-completion/completions/suite.bash`
: The generated bash completion script.

`docs/_build/man/suite.1`
: The generated man page, installed by `make install`.

## ENVIRONMENT

`NO_COLOR`
: Disable color when `--color=auto`.

`FORCE_COLOR`
: Force color when `--color=auto`.

`TERM`
: When set to `dumb`, color is disabled for `--color=auto`.

`XDG_CONFIG_HOME`
: Base directory for the configuration file. Defaults to `~/.config`.

`XDG_DATA_HOME`
: Base directory for the completion script. Defaults to `~/.local/share`.

`BASH_COMPLETION_USER_DIR`
: When set, its first non-empty colon-separated entry overrides the
  completion directory.

The completion script requires bash >= 4.4. Automatic loading requires
bash-completion >= 2.18. zsh is not supported.

## SEE ALSO

The project home page: <https://github.com/8cylinder/suite>
