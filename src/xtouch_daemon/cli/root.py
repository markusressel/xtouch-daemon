"""
Not as root: the daemon runs the commands of its configuration, and as root they would run as root. Commands that
run nothing and read no configuration of the user (`schema`, `simulate`, `--help`, `--version`) still work.
"""

import functools
import os
from typing import Any

import click

ALLOWED_AS_ROOT = frozenset({"schema", "simulate"})
"""The commands that run nothing and read no configuration of the user: root may use them."""

REFUSED = (
    "xtouch-daemon runs as your user, not as root: the commands of the configuration would run as root. "
    "Run it without sudo, e.g. as the systemd user service of `xtouch-daemon install-service`."
)


def refuse_root() -> None:
    """A ClickException if the effective user is root."""
    if os.geteuid() == 0:
        raise click.ClickException(REFUSED)


def not_as_root(command: click.Command) -> click.Command:
    """`command`, which fails as root before it does anything (its `--help` still works)."""
    callback = command.callback
    assert callback is not None, f"{command.name} has no callback"

    @functools.wraps(callback)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        refuse_root()
        return callback(*args, **kwargs)

    command.callback = guarded
    return command
