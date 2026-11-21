"""
Running as a systemd user service: readiness notifications, journal log levels, the unit file, and controlling the
service (its state, installing, starting and reloading it).

The release package (see packaging/build-release.sh) installs the daemon to `PACKAGE_ROOT` and its unit to
`PACKAGED_UNIT`. A unit in the user's configuration (`unit_path()`) overrides it: systemd prefers it by name.
"""

import functools
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import xtouch_daemon

UNIT_NAME = "xtouch-daemon.service"
PACKAGED_UNIT = Path("/usr/lib/systemd/user") / UNIT_NAME
"""The unit of the release package, which runs `/usr/bin/xtouch-daemon`."""
PACKAGE_ROOT = Path("/usr/lib/xtouch-daemon")
"""Where the release package installs the daemon, with its own Python."""

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
    except ValueError, OSError:
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


def runs_packaged() -> bool:
    """Whether this program is the one of the release package (also the GUI's, which uses the daemon's packages)."""
    return Path(xtouch_daemon.__file__).resolve().is_relative_to(PACKAGE_ROOT)


def uses_packaged_unit() -> bool:
    """Whether installing the service takes the unit of the package instead of writing one: for its own program."""
    return runs_packaged() and PACKAGED_UNIT.exists()


def overrides_packaged_unit() -> bool:
    """Whether a unit in the user's configuration hides the one of the package."""
    return PACKAGED_UNIT.exists() and unit_path().exists()


# -- controlling the service --------------------------------------------------------------------------------------

type Runner = Callable[[list[str]], str]
"""Runs a command and returns its output; raises `ServiceError` when it fails."""


class ServiceError(Exception):
    """A systemctl command that failed, with a message for the user."""


def run_command(command: list[str], timeout: float | None = None) -> str:
    """The output of `command`; `timeout`: seconds it may take (None: as long as it takes)."""
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ServiceError(f"{' '.join(command)} did not answer in {timeout:g} s") from e
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
    unit: Path | None = None
    """The unit file systemd read (the package's or one in the user's configuration), None while not installed."""
    program: str | None = None
    """The program the unit starts (its `ExecStart`)."""

    @property
    def running(self) -> bool:
        return self.active in ("active", "reloading")

    @property
    def packaged(self) -> bool:
        """Whether the unit in effect is the one of the release package."""
        return self.unit == PACKAGED_UNIT

    def describe(self) -> str:
        if not self.installed:
            return "not installed"
        if self.running:
            return "running" if self.enabled else "running, not enabled"
        return "stopped" if self.active == "inactive" else self.active


class Service:
    """The systemd user service of the daemon: its state, installing, starting, stopping and reloading it."""

    def __init__(self, run: Runner | None = None, wait: bool = True, timeout: float | None = None):
        """`timeout`: seconds a command of `systemctl` may take, e.g. while the user's service manager hangs."""
        self._run = run or functools.partial(run_command, timeout=timeout)
        self._wait = wait
        """
        Whether starting, restarting and stopping wait until the service did (`systemctl` waits for the end of the
        daemon, its shutdown sequence included). The GUI doesn't: meanwhile it draws the device and may be the device
        (the virtual one), which the daemon still talks to.
        """

    def _job(self, *args: str) -> list[str]:
        """A systemctl command that changes the service: queued only (`--no-block`) unless the service waits."""
        return _systemctl(*args, UNIT_NAME) if self._wait else _systemctl(*args, "--no-block", UNIT_NAME)

    def state(self) -> ServiceState:
        output = self._run(
            _systemctl("show", UNIT_NAME, "--property=LoadState,ActiveState,UnitFileState,FragmentPath,ExecStart")
        )
        properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        # ExecStart={ path=/usr/bin/xtouch-daemon ; argv[]=/usr/bin/xtouch-daemon run ; ... }
        program = re.search(r"\bpath=(\S+)", properties.get("ExecStart", ""))
        return ServiceState(
            installed=properties["LoadState"] == "loaded",
            active=properties["ActiveState"],
            enabled=properties["UnitFileState"] == "enabled",
            unit=Path(properties["FragmentPath"]) if properties.get("FragmentPath") else None,
            program=program[1] if program else None,
        )

    def install(self, executable: str, start: bool) -> Path | None:
        """
        Sets the service up; with `start`, also enables and starts it. The program of the release package takes the
        unit the package installed (`PACKAGED_UNIT`); any other one writes a unit that runs `executable` into the
        user's configuration. Returns the file written, None for the unit of the package.
        """
        path = None
        if not uses_packaged_unit():
            path = unit_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(unit_file(executable), encoding="utf-8")
        self._run(_systemctl("daemon-reload"))
        if start:
            self.start()
        return path

    def remove_override(self) -> Path:
        """
        Removes the unit in the user's configuration, so the one of the package is in effect. The service stays
        enabled if it was, and a running one restarts with the package's program. Returns the file removed.
        """
        state = self.state()
        path = unit_path()
        # the link that enables it points to the file that goes
        if state.enabled:
            self._run(_systemctl("disable", UNIT_NAME))
        path.unlink()
        self._run(_systemctl("daemon-reload"))
        if state.enabled:
            self._run(_systemctl("enable", UNIT_NAME))
        if state.running:
            self.restart()
        return path

    def start(self) -> None:
        """Enables the service and starts it."""
        self._run(self._job("enable", "--now"))

    def restart(self) -> None:
        self._run(self._job("restart"))

    def stop(self) -> None:
        """Stops the service; it stays enabled, so it starts again with the next session."""
        self._run(self._job("stop"))
