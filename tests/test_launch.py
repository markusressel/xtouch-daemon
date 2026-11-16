import logging
import os
import re
import sys
import threading
from pathlib import Path

import pytest

from tests.conftest import FakeLauncher
from xtouch_daemon import launch as launch_module
from xtouch_daemon.launch import LAUNCH_DEBOUNCE, LAUNCH_TIMEOUT, LaunchButton, Launcher, program_name, unit_name
from xtouch_daemon.protocol import Led

REAL_SPAWN = launch_module.spawn_detached
"""For tests of it with harmless programs of their own; `conftest.no_launches` replaces it in the module."""

MUMBLE = ("mumble", "mumble://markus@voice.example.org/Gaming")


def test_the_program_and_the_unit_of_a_command():
    assert program_name(("/usr/bin/Mumble", "x")) == "mumble"
    assert re.fullmatch(r"xtouch-launch-mumble-[0-9a-f]{6}", unit_name(MUMBLE))
    assert unit_name(MUMBLE) != unit_name(MUMBLE)
    assert re.fullmatch(r"xtouch-launch-org-app-v2-[0-9a-f]{6}", unit_name(("Org.App_v2",)))
    assert re.fullmatch(r"xtouch-launch-app-[0-9a-f]{6}", unit_name(("...",)))


def test_a_user_manager_is_there_with_its_socket(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    assert not launch_module.has_user_manager()
    (runtime_dir / "systemd").mkdir(parents=True)
    (runtime_dir / "systemd" / "private").touch()
    assert launch_module.has_user_manager()
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert not launch_module.has_user_manager()


def test_with_systemd_a_transient_service_runs_it(caplog: pytest.LogCaptureFixture):
    launcher = FakeLauncher()
    with caplog.at_level(logging.INFO):
        assert launcher.launch(MUMBLE, "Strip 3")
    (command,) = launcher.spawned
    assert command[:4] == ["/usr/bin/systemd-run", "--user", "--quiet", "--collect"]
    assert re.fullmatch(r"--unit=xtouch-launch-mumble-[0-9a-f]{6}", command[4])
    assert command[5:] == ["--property=WorkingDirectory=~", "--", *MUMBLE]
    assert "Strip 3: launched mumble mumble://markus@voice.example.org/Gaming" in caplog.text


def test_without_systemd_the_command_itself_runs():
    without_manager = FakeLauncher(user_manager=False)
    assert without_manager.launch(MUMBLE, "Strip 1")
    without_systemd_run = FakeLauncher()
    without_systemd_run.missing.add("systemd-run")
    assert without_systemd_run.launch(MUMBLE, "Strip 1")
    assert without_manager.spawned == without_systemd_run.spawned == [list(MUMBLE)]


def test_a_missing_program_is_a_warning(caplog: pytest.LogCaptureFixture):
    launcher = FakeLauncher()
    launcher.missing.add("mumble")
    assert not launcher.launch(MUMBLE, "Strip 1")
    assert launcher.spawned == []
    assert "Strip 1: can't launch mumble: there is no such program (in PATH)" in caplog.text


def test_a_start_that_fails_is_a_warning(caplog: pytest.LogCaptureFixture):
    def fail(command: list[str]) -> None:
        raise PermissionError(13, "Permission denied")

    launcher = Launcher(fail, lambda program: f"/usr/bin/{program}", lambda: False)
    assert not launcher.launch(MUMBLE, "Strip 1")
    assert "Strip 1: can't launch mumble: [Errno 13] Permission denied" in caplog.text


def test_the_default_spawn_is_used_late():
    # the tests replace it (conftest.no_launches): nothing starts for real
    with pytest.raises(AssertionError, match="a test would launch"):
        Launcher(which=lambda program: program, user_manager=lambda: False).launch(("true",), "Strip 1")


def wait_for_reaper(name: str) -> None:
    for thread in threading.enumerate():
        if thread.name == name:
            thread.join(5)


def test_a_detached_process_is_in_a_session_of_its_own(tmp_path: Path):
    # a harmless program of the tests, not an application of the machine
    out = tmp_path / "session"
    REAL_SPAWN(
        [
            sys.executable,
            "-c",
            f"import os, sys; open({str(out)!r}, 'w').write(f'{{os.getsid(0)}} {{sys.stdin.read()!r}}')",
        ]
    )
    wait_for_reaper(f"reap {sys.executable}")
    session, stdin = out.read_text().split(" ")
    assert int(session) != os.getsid(0)
    assert stdin == "''"


def test_a_detached_process_that_fails_is_logged(caplog: pytest.LogCaptureFixture):
    REAL_SPAWN([sys.executable, "-c", "raise SystemExit(3)"])
    wait_for_reaper(f"reap {sys.executable}")
    assert re.search(rf"{re.escape(sys.executable)} exited with 3 after \d+\.\d s", caplog.text)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_select_launches_while_the_application_does_not_run():
    launcher, clock = FakeLauncher(), Clock()
    button = LaunchButton(MUMBLE, launcher, "Strip 1", clock=clock)
    assert button.led(running=False) == Led.OFF
    assert not button.press(running=True)
    assert launcher.spawned == []
    assert button.press(running=False)
    assert len(launcher.spawned) == 1
    assert button.led(running=False) == Led.FLASH
    # a second press while it comes does nothing
    clock.now += LAUNCH_DEBOUNCE - 0.1
    assert not button.press(running=False)
    assert len(launcher.spawned) == 1
    # it is there
    assert button.led(running=True) == Led.ON
    assert button.led(running=False) == Led.OFF


def test_a_launch_that_does_not_show_up_stops_flashing(caplog: pytest.LogCaptureFixture):
    launcher, clock = FakeLauncher(), Clock()
    button = LaunchButton(MUMBLE, launcher, "Strip 1", clock=clock)
    button.press(running=False)
    clock.now += LAUNCH_DEBOUNCE
    # after the debounce it may be pressed again
    assert button.press(running=False)
    assert len(launcher.spawned) == 2
    clock.now += LAUNCH_TIMEOUT - 0.1
    assert button.led(running=False) == Led.FLASH
    clock.now += 0.1
    assert button.led(running=False) == Led.OFF
    assert "Strip 1: mumble did not show up in 15 s" in caplog.text


def test_a_launch_that_fails_does_not_flash():
    launcher = FakeLauncher()
    launcher.missing.add("mumble")
    button = LaunchButton(MUMBLE, launcher, "Strip 1")
    assert not button.press(running=False)
    assert button.led(running=False) == Led.OFF


def test_launch_when_running_launches_always():
    launcher, clock = FakeLauncher(), Clock()
    button = LaunchButton(MUMBLE, launcher, "Strip 1", always=True, clock=clock)
    assert button.press(running=True)
    # the debounce is for applications that are not up yet
    assert button.press(running=True)
    assert len(launcher.spawned) == 2
    assert button.led(running=True) == Led.ON


def test_the_program_of_the_command_runs():
    button = LaunchButton(("/usr/bin/Mumble",), FakeLauncher(), "Strip 1")
    assert button.program_runs(frozenset({"mumble"}))
    assert not button.program_runs(frozenset({"mumble-overlay"}))
