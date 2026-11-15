from pathlib import Path

import pytest

from xtouch_daemon.config import parse_config
from xtouch_daemon.gui.domain.status import Status, Tone, preview_status, sync_status
from xtouch_daemon.instance import Instance
from xtouch_daemon.live import Snapshot, fingerprint

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
