"""
Running as a systemd user service: readiness notifications, journal log levels, the unit file, and controlling the
service (its state, installing, starting and reloading it).
"""

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

UNIT_NAME = "xtouch-daemon.service"

UNIT_TEMPLATE = """\
[Unit]
Description=Behringer X-Touch Extender as a hardware mixer for PipeWire
Documentation=https://github.com/markusressel/xtouch-daemon
After=pipewire.service pipewire-pulse.service wireplumber.service
Wants=pipewire-pulse.service

[Service]
Type=notify
ExecStart={exec_start} run
ExecReload=kill -HUP $MAINPID
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""


def notify(*states: str) -> bool:
    """
    Tells systemd about the state of the service (e.g. `READY=1`, `STATUS=...`), if it runs as a `Type=notify`
    service. False when it does not.
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
            sock.sendto("\n".join(states).encode(), address)
    except OSError:
        return False
    return True


def reloading() -> bool:
    """For `systemctl reload`: the reload starts now (systemd wants the monotonic time with it)."""
    return notify("RELOADING=1", f"MONOTONIC_USEC={time.clock_gettime_ns(time.CLOCK_MONOTONIC) // 1000}")


def under_journal() -> bool:
    """Whether stderr goes to the journal (it adds the time itself, and takes the level from a prefix)."""
    stream = os.environ.get("JOURNAL_STREAM")
    if not stream:
        return False
    try:
        device, inode = (int(part) for part in stream.split(":"))
        stat = os.fstat(sys.stderr.fileno())
    except (ValueError, OSError):
        return False
    return (stat.st_dev, stat.st_ino) == (device, inode)


_SYSLOG_PRIORITIES = {
    logging.CRITICAL: 2,
    logging.ERROR: 3,
    logging.WARNING: 4,
    logging.INFO: 6,
    logging.DEBUG: 7,
}


class JournalFormatter(logging.Formatter):
    """Prefixes every line with its syslog priority (`<4>`), which the journal reads as the level of the entry."""

    def format(self, record: logging.LogRecord) -> str:
        priority = _SYSLOG_PRIORITIES.get(record.levelno, 6)
        return "\n".join(f"<{priority}>{line}" for line in super().format(record).splitlines())


def setup_logging(level: int) -> None:
    handler = logging.StreamHandler()
    if under_journal():
        handler.setFormatter(JournalFormatter("%(name)s: %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "systemd" / "user" / UNIT_NAME


def unit_file(executable: str) -> str:
    return UNIT_TEMPLATE.format(exec_start=executable)


# -- controlling the service --------------------------------------------------------------------------------------

type Runner = Callable[[list[str]], str]
"""Runs a command and returns its output; raises `ServiceError` when it fails."""


class ServiceError(Exception):
    """A systemctl command that failed, with a message for the user."""


def run_command(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise ServiceError(f"{command[0]} is not installed: is this a systemd system?") from e
    except subprocess.CalledProcessError as e:
        reason = e.stderr.strip() or f"exit code {e.returncode}"
        raise ServiceError(f"{' '.join(command)} failed: {reason}") from e
    return result.stdout


def executable() -> str:
    """The command that starts the daemon: the installed `xtouch-daemon`, or the program that runs now."""
    return shutil.which("xtouch-daemon") or str(Path(sys.argv[0]).resolve())


def _systemctl(*args: str) -> list[str]:
    return ["systemctl", "--user", *args]


@dataclass(frozen=True)
class ServiceState:
    """What systemd knows about the user service."""

    installed: bool
    active: str
    """systemd's `ActiveState`: active, reloading, inactive, failed, activating, deactivating."""
    enabled: bool
    """Whether it starts with the session."""

    @property
    def running(self) -> bool:
        return self.active in ("active", "reloading")

    def describe(self) -> str:
        if not self.installed:
            return "not installed"
        if self.running:
            return "running" if self.enabled else "running, not enabled"
        return "stopped" if self.active == "inactive" else self.active


class Service:
    """The systemd user service of the daemon: its state, installing, starting and reloading it."""

    def __init__(self, run: Runner | None = None):
        self._run = run or run_command

    def state(self) -> ServiceState:
        output = self._run(_systemctl("show", UNIT_NAME, "--property=LoadState,ActiveState,UnitFileState"))
        properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        return ServiceState(
            installed=properties["LoadState"] == "loaded",
            active=properties["ActiveState"],
            enabled=properties["UnitFileState"] == "enabled",
        )

    def install(self, executable: str, start: bool) -> Path:
        """Writes the unit file and makes systemd read it; with `start`, also enables and starts the service."""
        path = unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit_file(executable), encoding="utf-8")
        self._run(_systemctl("daemon-reload"))
        if start:
            self.start()
        return path

    def start(self) -> None:
        """Enables the service and starts it."""
        self._run(_systemctl("enable", "--now", UNIT_NAME))

    def restart(self) -> None:
        self._run(_systemctl("restart", UNIT_NAME))

    def reload(self) -> None:
        """Makes the running daemon read its configuration again."""
        self._run(_systemctl("reload", UNIT_NAME))
