"""
The devices the daemon saw, kept in its state directory for the suggestions of the GUI: remembered, kept up to date,
forgotten after a while or on request, and a file that can't be read or written never stops the daemon.
"""

import json
import logging
from pathlib import Path

import pytest

from tests.support.audio import output, source
from xtouch_daemon.audio.model import AudioState, Card
from xtouch_daemon.live.messages import KnownDevice
from xtouch_daemon.runtime.device_memory import FORGET_AFTER, TOUCH_INTERVAL, DeviceMemory

DAY = 24 * 3600.0


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


STATE = AudioState(
    outputs=(output("speaker", card="card0"), output("buds")),
    inputs=(source("mic"),),
    cards=(Card("card0", "analog"),),
)


def test_the_devices_seen_are_remembered_with_the_profile_of_their_card(tmp_path: Path):
    clock = Clock()
    path = tmp_path / "state" / "devices.json"
    memory = DeviceMemory(path, clock)

    assert memory.see(STATE)

    assert memory.known().devices == (
        KnownDevice("buds", "buds description", "output", None, None, clock.now),
        KnownDevice("speaker", "speaker description", "output", "card0", "analog", clock.now),
        KnownDevice("mic", "mic description", "input", None, None, clock.now),
    )
    # kept for the next start, and read back
    assert len(json.loads(path.read_text())) == 3
    assert DeviceMemory(path, clock).known() == memory.known()


def test_a_device_that_stays_is_written_again_only_now_and_then(tmp_path: Path):
    clock = Clock()
    path = tmp_path / "devices.json"
    memory = DeviceMemory(path, clock)
    memory.see(STATE)

    clock.now += 60
    assert not memory.see(STATE)
    clock.now += TOUCH_INTERVAL
    assert memory.see(STATE)
    assert memory.devices[("output", "buds")].seen == clock.now
    # what changed of it is kept at once: another profile of its card
    clock.now += 1
    assert memory.see(AudioState(outputs=STATE.outputs, cards=(Card("card0", "digital"),)))
    assert memory.devices[("output", "speaker")].profile == "digital"


def test_without_the_sound_server_nothing_is_seen(tmp_path: Path):
    memory = DeviceMemory(tmp_path / "devices.json", Clock())
    assert not memory.see(AudioState(connected=False))
    assert memory.known().devices == ()


def test_a_device_not_seen_for_a_long_time_is_forgotten(tmp_path: Path):
    clock = Clock()
    path = tmp_path / "devices.json"
    memory = DeviceMemory(path, clock)
    memory.see(STATE)

    clock.now += FORGET_AFTER - DAY
    memory.see(AudioState(outputs=(output("buds"),)))
    clock.now += 2 * DAY
    # also at the start of the next daemon
    assert [device.name for device in DeviceMemory(path, clock).known().devices] == ["buds"]
    memory.see(AudioState(outputs=(output("buds"),)))
    assert [device.name for device in memory.known().devices] == ["buds"]


def test_a_device_is_forgotten_on_request(tmp_path: Path):
    clock = Clock()
    path = tmp_path / "devices.json"
    memory = DeviceMemory(path, clock)
    memory.see(STATE)

    assert memory.forget("buds", "output")
    assert not memory.forget("buds", "output")
    # by its direction: an input of that name is another device
    assert not memory.forget("speaker", "input")
    assert [device.name for device in DeviceMemory(path, clock).known().devices] == ["speaker", "mic"]


def test_without_a_path_nothing_is_kept(tmp_path: Path):
    memory = DeviceMemory(None, Clock())
    assert memory.see(STATE)
    assert len(memory.known().devices) == 3
    assert not any(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '[{"name": "buds"}]',
        '[{"name": "a", "description": "b", "direction": "output", "card": null, '
        '"profile": null, "seen": "yesterday"}]',
    ],
)
def test_a_file_that_can_not_be_read_is_logged_and_starts_empty(
    tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
):
    path = tmp_path / "devices.json"
    path.write_text(content)

    assert DeviceMemory(path, Clock()).known().devices == ()
    assert f"Can't read the devices seen from {path}" in caplog.text


def test_a_file_that_can_not_be_written_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING)
    # a file where its directory would be
    (tmp_path / "state").write_text("")
    memory = DeviceMemory(tmp_path / "state" / "devices.json", Clock())

    assert memory.see(STATE)

    assert len(memory.known().devices) == 3
    assert "Can't keep the devices seen in" in caplog.text
