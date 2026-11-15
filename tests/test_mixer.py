import asyncio
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.conftest import FakeBackend, RecordingSurface, finish_tasks, output, settle, stream
from xtouch_daemon import mixer as mixer_module
from xtouch_daemon import protocol
from xtouch_daemon.audio.meter import CHUNK_BYTES, CaptureTarget
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config import Config, parse_config
from xtouch_daemon.mixer import Mixer
from xtouch_daemon.protocol import Button, RingMode
from xtouch_daemon.strips import EmptyStrip
from xtouch_daemon.strips.apps import AppGroupStrip, AutoStrip
from xtouch_daemon.strips.device import DeviceStrip

CONFIG = """
[behavior]
auto_hold = 5

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
device = "speaker"
label = "Speaker"

[[strip]]
type = "apps"
label = "Browser"
match = ["brave", "firefox"]
encoder = "volume"

[[strip]]
type = "empty"
"""

STATE = AudioState(
    outputs=(output("speaker", 50),),
    streams=(stream(1, "Brave"), stream(2, "Spotify", "spotify"), stream(3, "WEBRTC VoiceEngine", "Discord")),
    default_output="speaker",
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def config() -> Config:
    return parse_config(CONFIG)


@pytest.fixture
def capture_script(tmp_path: Path) -> str:
    """Plays pw-record: a capture that delivers one chunk of audio at half the full scale, then ends."""
    script = tmp_path / "fake-pw-record"
    script.write_text(
        f"#!{sys.executable}\n"
        "import struct, sys\n"
        f"sys.stdout.buffer.write(struct.pack('<f', 0.5) * {CHUNK_BYTES // 4})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


@pytest.fixture
async def mixer(surface: RecordingSurface, backend: FakeBackend, config: Config, clock: Clock, capture_script: str):
    mixer = Mixer(surface, backend, config, clock=clock, capture_command=capture_script)
    yield mixer
    mixer.close()
    await finish_tasks()


async def test_the_strips_are_built_from_the_configuration_and_the_rest_is_auto(mixer: Mixer) -> None:
    kinds = [type(controller) for controller in mixer.controllers]

    assert kinds == [DeviceStrip, AppGroupStrip, EmptyStrip, *[AutoStrip] * 5]
    assert mixer.claimed == (("brave", "firefox"),)


async def test_a_state_updates_every_strip_and_fills_the_auto_strips(mixer: Mixer, surface: RecordingSurface) -> None:
    mixer.on_state(STATE)

    assert surface.strips[0].text == ["Speaker", "50%"]
    assert surface.strips[1].text == ["Browser", "100%"]
    assert surface.strips[2].text == ["", ""]
    # the browser belongs to its group, the other applications get auto strips in their order
    assert surface.strips[3].text == ["Spotify", "100%"]
    assert surface.strips[4].text == ["Discord", "100%"]
    assert surface.strips[5].text == ["", ""]


async def test_a_state_sets_what_the_meters_capture(mixer: Mixer) -> None:
    mixer.on_state(STATE)

    assert mixer.meters[0].targets == {CaptureTarget("speaker", monitor=True)}
    assert mixer.meters[1].targets == {CaptureTarget("1", monitor=False)}
    assert mixer.meters[2].targets == set()
    assert mixer.meters[3].targets == {CaptureTarget("2", monitor=False)}


async def test_events_go_to_the_strip_they_happened_on(mixer: Mixer, backend: FakeBackend) -> None:
    mixer.on_state(STATE)

    mixer.on_event(protocol.FaderTouched(0, True))
    mixer.on_event(protocol.FaderMoved(0, protocol.fader_value(0.25)))
    mixer.on_event(protocol.FaderTouched(0, False))
    await settle()
    mixer.on_event(protocol.ButtonPressed(0, Button.MUTE, True))
    await settle()
    mixer.on_event(protocol.EncoderTurned(1, -10))
    await settle()
    mixer.on_event(protocol.EncoderPressed(1, True))
    await settle()

    assert backend.calls == [
        ("set_device_volume", Direction.OUTPUT, "speaker", 25),
        ("set_device_mute", Direction.OUTPUT, "speaker", True),
        ("set_stream_volume", 1, 90),
        ("set_stream_volume", 1, 100),
    ]


async def test_the_encoder_of_an_auto_strip_picks_its_application(mixer: Mixer, surface: RecordingSurface) -> None:
    mixer.on_state(STATE)
    assert [surface.strips[i].text[0] for i in (3, 4)] == ["Spotify", "Discord"]
    assert surface.strips[3].ring == (1, RingMode.DOT)

    # the next one: they swap
    mixer.on_event(protocol.EncoderTurned(3, 1))
    assert [surface.strips[i].text[0] for i in (3, 4)] == ["Discord", "Spotify"]
    assert surface.strips[3].ring == (11, RingMode.DOT)

    # an empty one picks too; a push pins
    mixer.on_event(protocol.EncoderTurned(5, -1))
    # from the strip that had it, which is left empty
    assert [surface.strips[i].text[0] for i in (3, 4, 5)] == ["", "Spotify", "Discord"]
    mixer.on_event(protocol.EncoderPressed(5, True))
    assert surface.strips[5].ring == (11, RingMode.WRAP)
    mixer.on_event(protocol.EncoderPressed(5, False))
    mixer.on_event(protocol.EncoderPressed(5, True))
    assert surface.strips[5].ring == (11, RingMode.DOT)


async def test_the_meters_show_the_captured_level(
    mixer: Mixer, surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mixer_module, "METER_INTERVAL", 0.01)
    mixer.on_state(STATE)

    task = asyncio.create_task(mixer.run())
    for _ in range(200):
        if surface.meters(0):
            break
        await asyncio.sleep(0.01)
    task.cancel()

    # half the full scale is -6 dB: 54 of 60 dB, the 11th of the 12 LEDs (5 dB each)
    assert surface.meters(0)[0] == 11
    # a strip without audio gets no level: the device lets its meter fall by itself
    assert surface.meters(2) == []


async def test_a_held_level_is_sent_again_and_again(
    mixer: Mixer, surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mixer_module, "METER_INTERVAL", 0.001)
    mixer.on_state(STATE)
    monkeypatch.setattr(mixer.controllers[2], "held_meter", lambda: 7)

    task = asyncio.create_task(mixer.run())
    for _ in range(200):
        if len(surface.meters(2)) >= 3:
            break
        await asyncio.sleep(0.005)
    task.cancel()

    # e.g. a level of Home Assistant: the device would let it fall
    assert surface.meters(2)[:3] == [7, 7, 7]


async def test_an_application_leaves_its_auto_strip_once_the_hold_time_is_over(
    mixer: Mixer, surface: RecordingSurface, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mixer_module, "METER_INTERVAL", 0.001)
    monkeypatch.setattr(mixer_module, "AUTO_INTERVAL", 0.002)
    mixer.on_state(STATE)
    mixer.on_state(AudioState(outputs=STATE.outputs, default_output="speaker"))
    assert surface.strips[3].text == ["Spotify", "idle"]

    # no new state comes, the time is over all the same
    clock.now = 6
    task = asyncio.create_task(mixer.run())
    for _ in range(100):
        if surface.strips[3].text[0] == "":
            break
        await asyncio.sleep(0.005)
    task.cancel()

    assert surface.strips[3].text == ["", ""]


async def test_without_auto_strips_nothing_is_refreshed(
    surface: RecordingSurface, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = parse_config('[[strip]]\ntype = "empty"\n' * 8)
    mixer = Mixer(surface, backend, config)
    refreshed: list[None] = []
    monkeypatch.setattr(mixer_module, "METER_INTERVAL", 0.001)
    monkeypatch.setattr(mixer_module, "AUTO_INTERVAL", 0.001)
    monkeypatch.setattr(mixer, "refresh", lambda: refreshed.append(None))

    task = asyncio.create_task(mixer.run())
    await asyncio.sleep(0.02)
    task.cancel()

    assert refreshed == []


async def test_closing_stops_the_meters(mixer: Mixer) -> None:
    mixer.on_state(STATE)

    mixer.close()

    assert all(meter.targets == set() for meter in mixer.meters)


async def test_a_meter_knows_whether_its_target_plays_from_the_latest_state(mixer: Mixer) -> None:
    target = CaptureTarget("speaker", monitor=True)
    mixer.on_state(STATE)
    assert not mixer.meters[0]._playing(target)

    mixer.on_state(AudioState(outputs=(output("speaker", 50, running=True),)))
    assert mixer.meters[0]._playing(target)


async def test_the_entities_of_home_assistant_strips_go_to_the_bridge(
    surface: RecordingSurface, backend: FakeBackend
) -> None:
    from haad_mqtt_autodiscovery.entity import MQTTEntity

    from xtouch_daemon.mqtt import MqttBridge
    from xtouch_daemon.strips.homeassistant import HomeAssistantStrip

    announced: list[dict[MQTTEntity, str | None]] = []

    class RecordingBridge(MqttBridge):
        async def set_entities(self, entities: Mapping[MQTTEntity, str | None]) -> None:
            announced.append(dict(entities))

    config = parse_config('[[strip]]\ntype = "homeassistant"\n' * 2 + '[mqtt]\nhost = "broker"\n')
    assert config.mqtt is not None
    bridge = RecordingBridge(config.mqtt)
    mixer = Mixer(surface, backend, config, bridge=bridge)

    task = asyncio.create_task(mixer.run())
    await settle()
    task.cancel()
    mixer.close()

    strips = [controller for controller in mixer.controllers if isinstance(controller, HomeAssistantStrip)]
    assert len(strips) == 2
    assert announced == [{**strips[0].entities, **strips[1].entities}]
    # fader, encoder, meter, two LCD lines, color, four LEDs, buttons
    assert len(announced[0]) == 2 * 11
