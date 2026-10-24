from __future__ import annotations

import os
from pathlib import Path

from .errors import SuiteError


def completion_path(prog: str = "suite") -> Path:
    """Return the bash completion script path for ``prog``."""
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "bash-completion" / "completions" / prog


def install_bash_completion(prog: str = "suite") -> Path:
    """Write the bash completion script for ``prog`` and return its path."""
    path = completion_path(prog)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_script(prog), encoding="utf-8")
    except OSError as exc:
        raise SuiteError(f"could not write completion script {path}: {exc}") from exc
    return path


def _script(prog: str) -> str:
    env_var = f"_{prog.upper().replace('-', '_')}_COMPLETE"
    function = f"_{prog.replace('-', '_')}_completion"
    return f"""\
{function}() {{
    local IFS=$'\\n'
    local response
    response=$(env \\
        COMP_WORDS="${{COMP_WORDS[*]}}" \\
        COMP_CWORD=$COMP_CWORD \\
        {env_var}=bash_complete \\
        {prog})
    for completion in $response; do
        IFS=',' read type value <<< "$completion"
        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=("$value")
        fi
    done
    return 0
}}
complete -o nosort -F {function} {prog}
"""
