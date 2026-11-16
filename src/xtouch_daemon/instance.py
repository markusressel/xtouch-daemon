"""
The running daemon, wherever it was started (the systemd service, a terminal, an IDE): `xtouch-daemon run` writes
`$XDG_RUNTIME_DIR/xtouch-daemon.json` with its process id and configuration file while it runs, so the GUI finds it
and can reload it, and a second daemon says which one has the device already.
"""

import contextlib
import json
import os
import signal
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

FILE_NAME = "xtouch-daemon.json"
SOCKET_NAME = "xtouch-daemon.sock"


class AlreadyRunning(Exception):
    def __init__(self, instance: Instance):
        super().__init__(f"xtouch-daemon runs already (process {instance.pid}, {instance.config})")
        self.instance = instance


@dataclass(frozen=True)
class Instance:
    pid: int
    config: Path
    """The configuration file it reads (again on a reload)."""
    systemd: bool
    """Whether systemd started it (the service): then systemd reloads and restarts it."""

    def reload(self) -> None:
        """Makes it read its configuration again (SIGHUP, what `systemctl reload` does too)."""
        os.kill(self.pid, signal.SIGHUP)


def runtime_file() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or str(Path(tempfile.gettempdir()) / f"xtouch-daemon-{os.getuid()}")
    return Path(runtime_dir) / FILE_NAME


def _alive(pid: int) -> bool:
    """Whether the process runs and is a daemon of this kind (the id of an ended one may belong to another program)."""
    try:
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError:
        return False
    return b"xtouch" in command_line and b"run" in command_line.split(b"\0")


def running() -> Instance | None:
    """The daemon that runs now, or None."""
    try:
        data = json.loads(runtime_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    instance = Instance(pid=data["pid"], config=Path(data["config"]), systemd=data["systemd"])
    return instance if _alive(instance.pid) else None


@contextlib.contextmanager
def registered(config: Path) -> Iterator[Instance]:
    """
    Makes this process the running daemon for as long as the block runs. `AlreadyRunning` if another one runs (a
    file left behind by one that was killed is replaced).
    """
    other = running()
    if other is not None and other.pid != os.getpid():
        raise AlreadyRunning(other)
    # systemd sets INVOCATION_ID for the processes of its units
    instance = Instance(pid=os.getpid(), config=config.expanduser().resolve(), systemd="INVOCATION_ID" in os.environ)
    path = runtime_file()
    # the user's own (the fallback in /tmp): the live view next to it takes requests
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"pid": instance.pid, "config": str(instance.config), "systemd": instance.systemd}),
        encoding="utf-8",
    )
    temporary.replace(path)
    try:
        yield instance
    finally:
        # unless another daemon took over the file meanwhile
        with contextlib.suppress(FileNotFoundError):
            if json.loads(path.read_text(encoding="utf-8"))["pid"] == instance.pid:
                path.unlink()


def socket_file() -> Path:
    """Where the running daemon serves the live view of the device (see `live.py`), next to the runtime file."""
    return runtime_file().with_name(SOCKET_NAME)
