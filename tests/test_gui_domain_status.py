import dataclasses
from pathlib import Path

import pytest

from xtouch_daemon.config.files import parse_config
from xtouch_daemon.gui.domain.status import Status, Tone, outdated, preview_status, sync_status, unit_status
from xtouch_daemon.live.messages import Snapshot, fingerprint
from xtouch_daemon.system import systemd
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import ServiceState

CONFIG = parse_config('[[strip]]\ntype = "output"\n')
OTHER = parse_config('[[strip]]\ntype = "input"\n')
PATH = Path("/home/me/config.toml")
DAEMON = Instance(42, PATH, systemd=True)


def snapshot(device: bool = True, config: str = fingerprint(CONFIG)) -> Snapshot:
    return Snapshot(config, device, sound_server=True, mqtt=None, strips=())


def test_the_preview_says_whether_it_is_live():
    assert preview_status(DAEMON, snapshot(), "X-Touch-Ext") == Status(
        "Live", Tone.GOOD, "The strips show what the device shows right now."
    )
    waiting = preview_status(DAEMON, snapshot(device=False), "X-Touch-Ext")
    assert (waiting.text, waiting.tone) == ("Live · X-Touch-Ext not connected", Tone.WARN)
    alone = preview_status(None, None, "X-Touch-Ext")
    assert (alone.text, alone.tone) == ("File preview", Tone.NEUTRAL)
    assert alone.tip.startswith("The daemon is not running")
    # a daemon from before the live view
    assert "process 42" in preview_status(DAEMON, None, "X-Touch-Ext").tip


@pytest.mark.parametrize(
    ("daemon", "live", "edited", "modified", "applying", "text", "tone"),
    [
        (None, None, 0, False, False, "Nothing runs this file.", Tone.NEUTRAL),
        (None, None, 0, True, False, "Nothing runs this file. There are unsaved changes.", Tone.NEUTRAL),
        (
            Instance(42, Path("/other.toml"), systemd=False),
            None,
            0,
            False,
            False,
            "The daemon reads /other.toml, not this file.",
            Tone.WARN,
        ),
        (DAEMON, None, 0, False, False, "The daemon reads this file.", Tone.NEUTRAL),
        (DAEMON, snapshot(), 0, False, False, "The device runs the saved file.", Tone.GOOD),
        (
            DAEMON,
            snapshot(),
            2,
            True,
            False,
            "The device runs the saved file. 2 strips with unsaved changes show how they will look.",
            Tone.GOOD,
        ),
        (DAEMON, snapshot(config=fingerprint(OTHER)), 0, False, True, "Applying the saved file…", Tone.NEUTRAL),
        (
            DAEMON,
            snapshot(config=fingerprint(OTHER)),
            0,
            False,
            False,
            "The device does not run the saved file yet.",
            Tone.WARN,
        ),
    ],
)
def test_whether_the_device_runs_the_saved_file(
    daemon: Instance | None, live: Snapshot | None, edited: int, modified: bool, applying: bool, text: str, tone: Tone
):
    status = sync_status(daemon, live, PATH, CONFIG, edited, modified, applying)
    assert (status.text, status.tone) == (text, tone)


def test_a_saved_file_with_errors_is_not_what_the_device_runs():
    assert sync_status(DAEMON, snapshot(), PATH, None, 0, False, False).tone == Tone.WARN


def test_a_live_preview_is_not_the_saved_file():
    preview = dataclasses.replace(snapshot(config=fingerprint(OTHER)), preview=True)

    # of this window, with the document as it is
    ours = sync_status(DAEMON, preview, PATH, CONFIG, 1, True, False, previewed=True)
    assert (ours.text, ours.tone) == (
        "The device runs the unsaved changes (live preview). Save to keep them.",
        Tone.WARN,
    )
    assert "brings back the saved file" in ours.tip
    # of another window, or of a version of the document before
    other = sync_status(DAEMON, preview, PATH, CONFIG, 1, True, False)
    assert other.text == (
        "The device runs a live preview, not the saved file. 1 strip with unsaved changes show how they will look."
    )
    assert other.tone == Tone.WARN


def test_the_unit_in_effect_is_the_packaged_one_or_where_it_comes_from():
    assert unit_status(ServiceState(installed=False, active="inactive", enabled=False), overrides=False) is None
    packaged = ServiceState(True, "active", True, unit=systemd.PACKAGED_UNIT, program="/usr/bin/xtouch-daemon")
    assert unit_status(packaged, overrides=False) == Status(
        "packaged", Tone.NEUTRAL, f"The unit of the package: {systemd.PACKAGED_UNIT}"
    )
    user_unit = Path("/home/me/.config/systemd/user/xtouch-daemon.service")
    checkout = ServiceState(
        True, "active", True, unit=user_unit, program="/home/me/xtouch-daemon/.venv/bin/xtouch-daemon"
    )
    assert unit_status(checkout, overrides=False) == Status(
        "from /home/me/xtouch-daemon/.venv/bin/xtouch-daemon", Tone.NEUTRAL, f"The unit {user_unit}"
    )
    # it hides the package's
    assert unit_status(checkout, overrides=True) == Status(
        "from /home/me/xtouch-daemon/.venv/bin/xtouch-daemon",
        Tone.WARN,
        f"The unit {user_unit}, which overrides the one of the package",
    )
    # systemd did not tell the program
    unknown = unit_status(ServiceState(True, "inactive", True, unit=user_unit), overrides=False)
    assert unknown is not None
    assert unknown.text == f"from {user_unit}"


def versioned(version: str | None) -> Snapshot:
    return Snapshot("abc", True, sound_server=True, mqtt=None, strips=(), daemon_version=version)


@pytest.mark.parametrize(
    ("active", "program", "version", "reason"),
    [
        (
            "active",
            "/usr/bin/xtouch-daemon",
            "0.1.0",
            "The daemon runs version 0.1.0, 0.2.0 is installed: restart it to run 0.2.0",
        ),
        (
            "reloading",
            "/usr/bin/xtouch-daemon",
            "0.1.0",
            "The daemon runs version 0.1.0, 0.2.0 is installed: restart it to run 0.2.0",
        ),
        # it runs the installed version
        ("active", "/usr/bin/xtouch-daemon", "0.2.0", None),
        # an older daemon does not tell its version
        ("active", "/usr/bin/xtouch-daemon", None, None),
        # the service runs another installation than the GUI
        ("active", "/opt/xtouch-daemon", "0.1.0", None),
        # it does not run
        ("inactive", "/usr/bin/xtouch-daemon", "0.1.0", None),
    ],
)
def test_a_service_that_runs_an_older_version_should_restart(
    active: str, program: str, version: str | None, reason: str | None
):
    state = ServiceState(True, active, True, unit=systemd.PACKAGED_UNIT, program=program)

    assert outdated(state, versioned(version), "0.2.0", "/usr/bin/xtouch-daemon") == reason


def test_without_a_live_view_the_version_is_not_known():
    state = ServiceState(True, "active", True, program="/usr/bin/xtouch-daemon")

    assert outdated(state, None, "0.2.0", "/usr/bin/xtouch-daemon") is None
