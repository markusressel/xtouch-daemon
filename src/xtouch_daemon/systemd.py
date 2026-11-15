"""Running as a systemd user service: readiness notifications, journal log levels and the unit file."""

import logging
import os
import socket
import sys
import time
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
