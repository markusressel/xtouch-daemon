"""
The machine the tests run on, which they never look at: the guard of `conftest.no_host`.
"""

import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

from tests.support.processes import child_processes

HOME = Path.home()
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR")
HOST_PATHS = (
    Path("/dev/snd"),
    Path("/proc/asound"),
    HOME / ".config",
    HOME / ".local" / "state",
    HOME / ".local" / "share" / "Mumble",
    HOME / ".local" / "share" / "flatpak",
    HOME / ".var",
    *([Path(RUNTIME_DIR)] if RUNTIME_DIR else []),
)
"""What the machine the tests run on has, and the tests never look at: devices, the user's files, the processes."""


class HostAccessError(Exception):
    """Not an OSError: code that expects a missing file does not take it for one."""


_host_access: list[str] | None = None
"""What the running test touched of the machine, None outside of a test (or in one marked `host`)."""


def _host_path(path: str) -> bool:
    absolute = Path(os.path.abspath(path))
    if absolute == Path("/proc"):
        # the list of the processes
        return True
    parts = absolute.parts
    if len(parts) > 2 and parts[1] == "proc" and parts[2].isdigit():
        pid = int(parts[2])
        # the processes of the tests themselves are theirs to look at
        return pid != os.getpid() and pid not in child_processes()
    return any(absolute.is_relative_to(host) for host in HOST_PATHS)


def _audit(event: str, args: tuple[object, ...]) -> None:
    global _host_access
    if _host_access is None or event not in ("open", "os.listdir", "os.scandir", "socket.connect"):
        return
    target = args[1] if event == "socket.connect" else args[0] if args else None
    if isinstance(target, bytes):
        target = target.decode(errors="replace")
    if isinstance(target, os.PathLike):
        target = os.fspath(target)
    if not isinstance(target, str) or not target or not _host_path(target):
        return
    accessed, guard = f"{event} {target}", _host_access
    _host_access = None
    try:
        guard.append(accessed)
    finally:
        _host_access = guard
    raise HostAccessError(f"a test touched the machine it runs on: {accessed}")


sys.addaudithook(_audit)


@contextlib.contextmanager
def guarded() -> Iterator[list[str]]:
    """Fails what touches the machine the tests run on (`HostAccessError`) while it lasts; the list has what did."""
    global _host_access
    accessed: list[str] = []
    _host_access = accessed
    try:
        yield accessed
    finally:
        _host_access = None
