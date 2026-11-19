import dataclasses
from pathlib import Path

from xtouch_daemon.config.files import parse_config
from xtouch_daemon.gui.domain.live_preview import previewed, unavailable
from xtouch_daemon.live.messages import FEATURES, Snapshot, fingerprint
from xtouch_daemon.system.instance import Instance

CONFIG = parse_config('[channel.out]\ntype = "output"\nlabel = "Out"\n[slots]\n1 = "out"\n')
PATH = Path("/home/me/config.toml")
DAEMON = Instance(42, PATH, systemd=True)
SNAPSHOT = Snapshot(fingerprint(CONFIG), True, sound_server=True, mqtt=None, strips=(), features=FEATURES)


def test_trying_changes_needs_a_daemon_of_this_user_that_runs_this_file_and_knows_previews():
    def why(daemon: Instance | None, snapshot: Snapshot | None, owned: bool) -> str | None:
        reason = unavailable(daemon, snapshot, PATH, owned)
        return None if reason is None else reason.why

    assert why(DAEMON, SNAPSHOT, owned=True) is None
    assert why(None, None, owned=False) == "No daemon runs: start the service to preview the changes on the device."
    elsewhere = Instance(42, Path("/other.toml"), systemd=False)
    assert unavailable(elsewhere, SNAPSHOT, PATH, owned=True) is not None
    assert why(DAEMON, None, owned=False) == (
        "No live view from the daemon (process 42): restart it to preview changes on the device."
    )
    # the configuration has secrets: it goes only to a daemon of this user
    assert "another user" in (why(DAEMON, SNAPSHOT, owned=False) or "")
    older = dataclasses.replace(SNAPSHOT, features=())
    assert why(DAEMON, older, owned=True) == (
        "The daemon that runs is too old to preview changes on the device: restart it to run the installed version."
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
    assert not previewed(
        preview, parse_config('[channel.mic]\ntype = "input"\nlabel = "Mic"\n[slots]\n1 = "mic"\n'), running=True
    )
