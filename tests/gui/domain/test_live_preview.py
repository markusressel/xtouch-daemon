import dataclasses
from pathlib import Path

from xtouch_daemon.config.files import parse_config
from xtouch_daemon.gui.domain.live_preview import preview_pill, previewed, unavailable
from xtouch_daemon.gui.domain.status import Tone
from xtouch_daemon.live.messages import FEATURES, Snapshot, fingerprint
from xtouch_daemon.system.instance import Instance

CONFIG = parse_config('[[strip]]\ntype = "output"\n')
PATH = Path("/home/me/config.toml")
DAEMON = Instance(42, PATH, systemd=True)
SNAPSHOT = Snapshot(fingerprint(CONFIG), True, sound_server=True, mqtt=None, strips=(), features=FEATURES)


def test_the_live_preview_needs_a_daemon_of_this_user_that_runs_this_file_and_knows_previews():
    assert unavailable(DAEMON, SNAPSHOT, PATH, owned=True) is None

    assert unavailable(None, None, PATH, owned=False) == (
        "No daemon runs: start the service to preview the changes on the device."
    )
    elsewhere = Instance(42, Path("/other.toml"), systemd=False)
    assert unavailable(elsewhere, SNAPSHOT, PATH, owned=True) == "The daemon runs /other.toml, not this file."
    assert unavailable(DAEMON, None, PATH, owned=False) == (
        "No live view from the daemon (process 42): restart it for a live preview."
    )
    # the configuration has secrets: it goes only to a daemon of this user
    assert "another user" in (unavailable(DAEMON, SNAPSHOT, PATH, owned=False) or "")
    older = dataclasses.replace(SNAPSHOT, features=())
    assert unavailable(DAEMON, older, PATH, owned=True) == (
        "The daemon that runs is too old for a live preview: restart it to run the installed version."
    )


def test_the_device_shows_the_document_once_its_preview_runs():
    preview = dataclasses.replace(SNAPSHOT, preview=True)

    assert previewed(preview, CONFIG, running=True)
    # not ours, or not yet
    assert not previewed(preview, CONFIG, running=False)
    assert not previewed(SNAPSHOT, CONFIG, running=True)
    assert not previewed(None, CONFIG, running=True)
    # the document has problems, or changed since
    assert not previewed(preview, None, running=True)
    assert not previewed(preview, parse_config('[[strip]]\ntype = "input"\n'), running=True)


def test_the_pill_says_what_the_device_runs():
    assert preview_pill(on=False, running=False, modified=True, problems=False) is None
    running = preview_pill(on=True, running=True, modified=True, problems=False)
    assert running is not None
    assert (running.text, running.tone) == ("Previewing unsaved changes", Tone.WARN)
    assert "Save to keep it" in running.tip
    on_its_way = preview_pill(on=True, running=False, modified=True, problems=False)
    assert on_its_way is not None
    assert on_its_way.text == "Live preview…"
    unchanged = preview_pill(on=True, running=False, modified=False, problems=False)
    assert unchanged is not None
    assert (unchanged.text, unchanged.tone) == ("Live preview", Tone.NEUTRAL)
    paused = preview_pill(on=True, running=True, modified=True, problems=True)
    assert paused is not None
    assert (paused.text, paused.tone) == ("Live preview paused", Tone.WARN)
