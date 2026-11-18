"""
Starting applications from the Select button of a strip (`launch`), detached from the daemon: a restart of the
daemon's service must not end them. See docs/development/design/launch.md.

The command comes only from the configuration (the file, or a live preview of the same user) and runs without a
shell. Home Assistant can't start anything.
"""

import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from xtouch_daemon.hardware.protocol import Led

_LOGGER = logging.getLogger(__name__)

LAUNCH_DEBOUNCE = 5.0
"""Seconds after a launch in which Select does not launch again, unless the application is there already."""
LAUNCH_TIMEOUT = 15.0
"""Seconds the Select LED flashes after a launch at most, while the application does not show up."""

type Spawn = Callable[[list[str]], None]
"""Starts a process with these arguments and does not wait for it; raises OSError when it can't."""


def program_name(command: Sequence[str]) -> str:
    """The file name of the program of a command, in lower case, as `processes.running_processes()` names processes."""
    return Path(command[0]).name.lower()


def unit_name(command: Sequence[str]) -> str:
    """A name for the transient unit of a launch, e.g. `xtouch-launch-mumble-1a2b3c`: unique, and says what it is."""
    slug = re.sub(r"[^a-z0-9]+", "-", program_name(command)).strip("-")[:32] or "app"
    return f"xtouch-launch-{slug}-{secrets.token_hex(3)}"


def has_user_manager() -> bool:
    """Whether a systemd user manager runs for this user (its private socket is there), which `systemd-run` needs."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return runtime is not None and (Path(runtime) / "systemd" / "private").exists()


def spawn_detached(command: list[str]) -> None:
    """
    Starts the command in a session of its own, without the daemon's input and output, and waits for it in a thread
    of its own, so it does not stay a zombie. An exit with an error is logged.
    """
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def reap() -> None:
        code = process.wait()
        if code != 0:
            _LOGGER.warning(f"{command[0]} exited with {code} after {time.monotonic() - started:.1f} s")

    threading.Thread(target=reap, name=f"reap {command[0]}", daemon=True).start()


class Launcher:
    """
    Starts commands detached from the daemon: as a transient systemd user service (`systemd-run --user`), or without
    systemd as a process in a session of its own.
    """

    def __init__(
        self,
        spawn: Spawn | None = None,
        which: Callable[[str], str | None] = shutil.which,
        user_manager: Callable[[], bool] = has_user_manager,
    ):
        self._spawn = spawn
        """By default `spawn_detached()`."""
        self._which = which
        self._user_manager = user_manager

    def command_for(self, command: Sequence[str]) -> list[str]:
        """What runs for `command`: through `systemd-run` while there is a user manager, else the command itself."""
        systemd_run = self._which("systemd-run")
        if systemd_run is None or not self._user_manager():
            return list(command)
        return [
            systemd_run,
            "--user",
            "--quiet",
            "--collect",
            f"--unit={unit_name(command)}",
            "--property=WorkingDirectory=~",
            "--",
            *command,
        ]

    def launch(self, command: Sequence[str], what: str) -> bool:
        """
        Starts the command; `what` names it in the log (e.g. the strip). False when it can't be started (its program
        is not there), which is logged.
        """
        if self._which(command[0]) is None:
            _LOGGER.warning(f"{what}: can't launch {command[0]}: there is no such program (in PATH)")
            return False
        try:
            (self._spawn or spawn_detached)(self.command_for(command))
        except OSError as e:
            _LOGGER.warning(f"{what}: can't launch {command[0]}: {e}")
            return False
        _LOGGER.info(f"{what}: launched {' '.join(command)}")
        return True


class LaunchButton:
    """
    What Select does on a strip with `launch`: starts the command while the application does not run (or always, with
    `always`), at most once per LAUNCH_DEBOUNCE while it does not show up. Its LED flashes while the application is
    being launched, and is on while it runs.
    """

    def __init__(
        self,
        command: tuple[str, ...],
        launcher: Launcher,
        what: str,
        always: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.command = command
        self.launcher = launcher
        self.what = what
        self.always = always
        self.program = program_name(command)
        """Its process counts as the application running, e.g. a silent Mumble."""
        self._clock = clock
        self._started: float | None = None
        """When it launched last, while the LED flashes."""

    def program_runs(self, processes: Collection[str]) -> bool:
        return self.program in processes

    def launching(self, running: bool) -> bool:
        """Whether the application is being launched: since less than LAUNCH_TIMEOUT, and it does not run yet."""
        if self._started is None:
            return False
        if running:
            self._started = None
            return False
        if self._clock() - self._started >= LAUNCH_TIMEOUT:
            _LOGGER.warning(f"{self.what}: {self.command[0]} did not show up in {LAUNCH_TIMEOUT:.0f} s")
            self._started = None
            return False
        return True

    def led(self, running: bool) -> Led:
        if self.launching(running):
            return Led.FLASH
        return Led.ON if running else Led.OFF

    def press(self, running: bool) -> bool:
        """Select was pressed: launches if it should. Whether it launched."""
        if running and not self.always:
            return False
        if self._started is not None and not running and self._clock() - self._started < LAUNCH_DEBOUNCE:
            _LOGGER.debug(f"{self.what}: {self.command[0]} is being launched already")
            return False
        if not self.launcher.launch(self.command, self.what):
            return False
        self._started = self._clock()
        return True
