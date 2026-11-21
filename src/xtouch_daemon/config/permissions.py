"""
Files of the configuration that other users can change. The daemon runs the commands of its configuration, so it
uses no file that another user could put a command into, as OpenSSH does with `StrictModes`. A secret that others can
read is only a warning: the daemon can't take it back.
"""

import logging
import os
import pwd
from pathlib import Path
from typing import Protocol

from xtouch_daemon.config.base import ConfigError

_LOGGER = logging.getLogger(__name__)

WRITABLE_BY_OTHERS = 0o022
"""The mode bits that let the group or the others change a file, or the files of a directory."""
READABLE_BY_OTHERS = 0o044
"""The mode bits that let the group or the others read a file."""


class Status(Protocol):
    """What `os.stat()` tells about a file that matters here."""

    @property
    def st_uid(self) -> int: ...
    @property
    def st_mode(self) -> int: ...


def places(path: Path) -> list[Path]:
    """
    What decides about the content of `path`: the file itself (the target, if it is a link), the directory it is in,
    and the directory of the link. Not the directories above them, e.g. `/home`.
    """
    target = path.resolve()
    found = [target, target.parent]
    link_directory = path.absolute().parent.resolve()
    if link_directory not in found:
        found.append(link_directory)
    return found


def problem(place: Path, status: Status, euid: int) -> str | None:
    """What makes `place` unsafe for the user `euid`, None if it is theirs or root's and only they write."""
    if status.st_uid not in (euid, 0):
        return (
            f"{place} belongs to {_user(status.st_uid)}, not to you, so the daemon does not use it: "
            f"make it yours with `sudo chown {_user(euid)} {place}`"
        )
    if status.st_mode & WRITABLE_BY_OTHERS:
        return f"other users can change {place}, so the daemon does not use it: fix it with `chmod go-w {place}`"
    return None


def check_safe(path: Path, euid: int | None = None) -> None:
    """ConfigError if a user other than `euid` (by default the one running) or root can change the file `path`."""
    user = os.geteuid() if euid is None else euid
    for place in places(path):
        try:
            status = place.stat()
        except OSError as e:
            raise ConfigError(f"can't check {place}: {e.strerror}") from e
        found = problem(place, status, user)
        if found is not None:
            raise ConfigError(found)


def warn_if_readable(path: Path, option: str) -> None:
    """Logs a warning if other users can read the secret in the file `path` (of the option `option`)."""
    try:
        mode = path.stat().st_mode
    except OSError:
        # reading it says what is wrong
        return
    if mode & READABLE_BY_OTHERS:
        _LOGGER.warning(f"{option}: other users can read {path}. Keep it to you with `chmod go-rw {path}`")


def _user(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)
