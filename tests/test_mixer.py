import asyncio
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.conftest import FakeBackend, FakeLauncher, RecordingSurface, finish_tasks, output, settle, stream
from xtouch_daemon import mixer as mixer_module
from xtouch_daemon import protocol
from xtouch_daemon.audio.meter import CHUNK_BYTES, CaptureTarget
from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Direction
from xtouch_daemon.config import Config, parse_config
from xtouch_daemon.mixer import Mixer
from xtouch_daemon.protocol import Button, Led, RingMode
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
        # 100 % at 77 % of the travel
        ("set_device_volume", Direction.OUTPUT, "speaker", 32),
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
    from haad_mqtt_autodiscovery.entity.select import MQTTSelect

    from xtouch_daemon.mqtt import MqttBridge
    from xtouch_daemon.strips.homeassistant import HomeAssistantStrip

    announced: list[dict[MQTTEntity, str | None]] = []
    kept: list[frozenset[str]] = []
    previews: list[bool] = []

    class RecordingBridge(MqttBridge):
        async def set_entities(
            self, entities: Mapping[MQTTEntity, str | None], keep: frozenset[str] = frozenset(), preview: bool = False
        ) -> None:
            announced.append(dict(entities))
            kept.append(keep)
            previews.append(preview)

    config = parse_config('[[strip]]\ntype = "homeassistant"\n' * 2 + '[mqtt]\nhost = "broker"\n')
    assert config.mqtt is not None
    bridge = RecordingBridge(config.mqtt)
    shared = MQTTSelect("xtouch", "layout", "Layout", options=["default"])
    mixer = Mixer(surface, backend, config, bridge=bridge, shared_entities={shared: "default"}, keep=frozenset({"x"}))

    task = asyncio.create_task(mixer.run())
    await settle()
    task.cancel()
    mixer.close()

    strips = [controller for controller in mixer.controllers if isinstance(controller, HomeAssistantStrip)]
    assert len(strips) == 2
    assert announced == [{**strips[0].entities, **strips[1].entities, shared: "default"}]
    # fader, encoder, meter, two LCD lines, color, four LEDs, buttons; and the shared one
    assert len(announced[0]) == 2 * 11 + 1
    assert kept == [frozenset({"x"})]
    assert previews == [False]

    # the mixer of a preview of the GUI says so: the bridge keeps the entities of the file
    preview = Mixer(surface, backend, config, bridge=bridge, preview=True)
    task = asyncio.create_task(preview.run())
    await settle()
    task.cancel()
    preview.close()
    assert previews == [False, True]


LAYOUTS = """
[voip]
provider = "demo"
participants = ["Ann", "Bob", "Carol"]

[[strip]]
type = "output"
device = "speaker"

[[layout]]
name = "gaming"

[[layout.strip]]
type = "voip"
count = 2

[[layout.strip]]
type = "voip"

[[layout.strip]]
type = "inherit"
"""


async def test_a_mixer_drives_the_strips_of_a_layout(surface: RecordingSurface, backend: FakeBackend):
    from xtouch_daemon.strips.voip import VoipStrip
    from xtouch_daemon.voip.demo import DemoProvider

    config = parse_config(LAYOUTS)
    voip = DemoProvider(("Ann", "Bob", "Carol"))
    mixer = Mixer(surface, backend, config, capture_command="true", layout="gaming", voip=voip)
    first, second, third = mixer.controllers[:3]
    assert isinstance(first, VoipStrip)
    assert isinstance(second, VoipStrip)
    assert isinstance(third, VoipStrip)
    # two groups: one of two places, one of one
    assert first.group is second.group
    assert third.group is not first.group
    assert (first.slot, second.slot, third.slot) == (0, 1, 0)
    # the place of the default layout is not configured: auto
    assert isinstance(mixer.controllers[3], AutoStrip)
    assert mixer.layout == "gaming"

    mixer.on_state(STATE)
    assert [strip.text[0] for strip in surface.strips[:3]] == ["Ann", "Bob", "Ann"]
    # the provider tells a change: the strips show it
    await voip.set_muted("2", True)
    assert surface.strips[1].text[1] == "muted"
    mixer.close()
    await voip.set_muted("2", False)
    assert surface.strips[1].text[1] == "muted"


def test_an_inherited_voip_strip_stays_one_group(surface: RecordingSurface, backend: FakeBackend):
    from xtouch_daemon.strips.voip import VoipStrip
    from xtouch_daemon.voip.demo import DemoProvider

    config = parse_config(
        '[voip]\n[[strip]]\ntype = "voip"\ncount = 2\n'
        '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\n[[layout.strip]]\ntype = "inherit"\n'
    )
    mixer = Mixer(surface, backend, config, capture_command="true", layout="a", voip=DemoProvider(("A",)))
    first, second = mixer.controllers[:2]
    assert isinstance(first, VoipStrip)
    assert isinstance(second, VoipStrip)
    assert first.group is second.group
    mixer.close()


LAUNCH_CONFIG = """
[voip]
[[strip]]
type = "apps"
label = "VoIP"
match = ["discord"]
launch = ["mumble", "mumble://markus@voice.example.org/Gaming"]
[[strip]]
type = "voip"
launch = "mumble 'mumble://markus@voice.example.org/Gaming'"
"""


async def test_strips_with_launch_follow_the_processes(
    surface: RecordingSurface, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from xtouch_daemon.strips.voip import VoipStrip
    from xtouch_daemon.voip.demo import DemoProvider

    running = [frozenset({"bash"})]
    launcher = FakeLauncher()
    mixer = Mixer(
        surface,
        backend,
        parse_config(LAUNCH_CONFIG),
        capture_command="true",
        voip=DemoProvider(()),
        launcher=launcher,
        processes=lambda: running[0],
    )
    apps, voip = mixer.controllers[:2]
    assert isinstance(apps, AppGroupStrip)
    assert isinstance(voip, VoipStrip)
    assert apps.launch is not None
    assert voip.group.launch is not None
    assert voip.group.launch.what == "Strip 2"
    assert mixer.watches_processes
    assert mixer.processes == {"bash"}
    mixer.on_state(AudioState())

    mixer.on_event(protocol.ButtonPressed(0, Button.SELECT, True))
    assert len(launcher.spawned) == 1
    assert surface.strips[0].leds[Button.SELECT] == Led.FLASH

    # it shows up: the next look at the processes sees it
    running[0] = frozenset({"bash", "mumble"})
    monkeypatch.setattr(mixer_module, "METER_INTERVAL", 0.001)
    monkeypatch.setattr(mixer_module, "PROCESS_INTERVAL", 0.002)
    task = asyncio.create_task(mixer.run())
    for _ in range(100):
        if surface.strips[0].leds[Button.SELECT] == Led.ON:
            break
        await asyncio.sleep(0.005)
    task.cancel()
    assert surface.strips[0].leds[Button.SELECT] == Led.ON
    mixer.close()
    await finish_tasks()


async def test_without_launch_the_processes_are_not_read(surface: RecordingSurface, backend: FakeBackend) -> None:
    def processes() -> frozenset[str]:
        raise AssertionError("read the processes")

    mixer = Mixer(surface, backend, parse_config(CONFIG), capture_command="true", processes=processes)
    assert not mixer.watches_processes
    mixer.close()


# -- strips that collapse --------------------------------------------------------------------------------------------

FLOW = """
[behavior]
collapse_hold = 3
max_volume = 100

[[strip]]
type = "output"
device = "speaker"
label = "Out"

[[strip]]
type = "output"
device = "bluez_output.*"
label = "Buds"
collapse = true

[[strip]]
type = "apps"
label = "Browser"
match = ["brave"]

[[strip]]
type = "apps"
label = "Games"
match = [".exe"]

[[strip]]
type = "apps"
label = "VoIP"
match = ["discord"]

[[strip]]
type = "auto"

[[strip]]
type = "auto"

[[strip]]
type = "input"
device = "mic"
label = "Mic"

[[strip]]
type = "apps"
label = "Spotify"
match = ["spotify"]
collapse = true
"""

QUIET = AudioState(
    outputs=(output("speaker", 50),),
    streams=(stream(1, "Brave", volume=40), stream(2, "Spotify", "spotify", volume=70)),
    default_output="speaker",
)
BUDS_ON = AudioState(
    outputs=(*QUIET.outputs, output("bluez_output.buds", 30)),
    streams=QUIET.streams,
    default_output="speaker",
)


@pytest.fixture
async def flow_mixer(surface: RecordingSurface, backend: FakeBackend, clock: Clock, capture_script: str):
    mixer = Mixer(surface, backend, parse_config(FLOW), clock=clock, capture_command=capture_script)
    yield mixer
    mixer.close()
    await finish_tasks()


def labels(surface: RecordingSurface) -> list[str]:
    return [strip.text[0] for strip in surface.strips]


async def test_a_strip_with_nothing_to_control_gives_its_place_to_the_next(
    flow_mixer: Mixer, surface: RecordingSurface
) -> None:
    flow_mixer.on_state(QUIET)
    # from scratch: no hold time at the start
    assert labels(surface) == ["Out", "Browser", "Games", "VoIP", "", "", "Mic", "Spotify"]
    assert flow_mixer.placement == (0, 2, 3, 4, 5, 6, 7, 8)
    # its id is its place in the configuration, not on the device
    assert flow_mixer.controllers[8].strip.index == 8


async def test_a_device_that_appears_takes_its_place_and_the_others_move(
    flow_mixer: Mixer, surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    flow_mixer.on_state(QUIET)
    await surface.settled()
    assert surface.strips[1].fader == protocol.fader_value(0.4)

    flow_mixer.on_state(BUDS_ON)
    assert labels(surface) == ["Out", "Buds", "Browser", "Games", "VoIP", "", "", "Mic"]
    assert "Strips: Buds appears at 2, Browser moves to 3, Games moves to 4" in caplog.text
    assert "Spotify waits" in caplog.text
    await surface.settled()
    # the faders glide to the volumes of the strips they show now
    assert surface.strips[1].position == protocol.fader_value(0.3)
    assert surface.strips[2].position == protocol.fader_value(0.4)
    # the meters capture for the strips on the device only
    assert flow_mixer.meters[1].targets == {CaptureTarget("bluez_output.buds", monitor=True)}
    assert flow_mixer.meters[8].targets == set()


async def test_a_device_that_goes_away_gives_its_place_up_after_the_hold_time(
    flow_mixer: Mixer, surface: RecordingSurface, clock: Clock
) -> None:
    flow_mixer.on_state(BUDS_ON)
    flow_mixer.on_state(QUIET)
    assert labels(surface)[:3] == ["Out", "Buds", "Browser"]
    assert surface.strips[1].text[1] == "off"
    clock.now = 2.0
    flow_mixer.on_state(QUIET)
    assert labels(surface)[1] == "Buds"
    clock.now = 3.0
    flow_mixer.on_state(QUIET)
    assert labels(surface)[:3] == ["Out", "Browser", "Games"]


async def test_the_hold_time_ends_without_a_new_state(
    flow_mixer: Mixer, surface: RecordingSurface, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mixer_module, "METER_INTERVAL", 0.001)
    flow_mixer.on_state(BUDS_ON)
    flow_mixer.on_state(QUIET)
    task = asyncio.create_task(flow_mixer.run())
    await asyncio.sleep(0.01)
    assert labels(surface)[1] == "Buds"
    clock.now = 5.0
    for _ in range(100):
        await asyncio.sleep(0.001)
        if labels(surface)[1] == "Browser":
            break
    assert labels(surface)[1] == "Browser"
    assert flow_mixer.meters[8].targets == {CaptureTarget("2", monitor=False)}
    task.cancel()


@pytest.mark.parametrize(
    ("press", "release"),
    [
        (protocol.FaderTouched(2, True), protocol.FaderTouched(2, False)),
        (protocol.ButtonPressed(5, Button.SELECT, True), protocol.ButtonPressed(5, Button.SELECT, False)),
        (protocol.EncoderPressed(6, True), protocol.EncoderPressed(6, False)),
    ],
)
async def test_nothing_moves_under_a_finger(
    flow_mixer: Mixer, surface: RecordingSurface, press: protocol.StripEvent, release: protocol.StripEvent
) -> None:
    flow_mixer.on_state(QUIET)
    flow_mixer.on_event(press)
    flow_mixer.on_state(BUDS_ON)
    assert labels(surface)[1] == "Browser"
    flow_mixer.on_event(release)
    assert labels(surface)[1] == "Buds"
    assert flow_mixer.meters[1].targets == {CaptureTarget("bluez_output.buds", monitor=True)}


async def test_a_fader_moved_without_a_touch_holds_the_strips_too(flow_mixer: Mixer, surface: RecordingSurface) -> None:
    flow_mixer.on_state(QUIET)
    surface.strips[4].held = True
    flow_mixer.on_state(BUDS_ON)
    assert labels(surface)[1] == "Browser"
    surface.strips[4].held = False
    flow_mixer.on_state(BUDS_ON)
    assert labels(surface)[1] == "Buds"


async def test_events_go_to_the_strip_the_device_shows_there(
    flow_mixer: Mixer, surface: RecordingSurface, backend: FakeBackend
) -> None:
    flow_mixer.on_state(BUDS_ON)
    flow_mixer.on_event(protocol.FaderTouched(2, True))
    flow_mixer.on_event(protocol.FaderMoved(2, protocol.fader_value(0.25)))
    await settle()
    # the browser, which is the third strip of the device now
    assert backend.calls[-1] == ("set_stream_volume", 1, 25)


async def test_a_dark_strip_of_the_device_ignores_the_hand(
    surface: RecordingSurface, backend: FakeBackend, clock: Clock, capture_script: str
) -> None:
    config = parse_config(
        '[[strip]]\ntype = "output"\ndevice = "buds"\ncollapse = true\n' + '[[strip]]\ntype = "empty"\n' * 7
    )
    mixer = Mixer(surface, backend, config, clock=clock, capture_command=capture_script)
    mixer.on_state(QUIET)
    assert mixer.placement == (1, 2, 3, 4, 5, 6, 7, None)
    mixer.on_event(protocol.ButtonPressed(7, Button.MUTE, True))
    mixer.on_event(protocol.ButtonPressed(7, Button.MUTE, False))
    await settle()
    assert backend.calls == []
    mixer.close()
    # the strips of a closed mixer draw on the device no more
    mixer.strips[1].set_text(0, "gone")
    assert surface.strips[0].text[0] == ""
    await finish_tasks()


async def test_without_a_sound_server_the_strips_stay_where_they_are(
    flow_mixer: Mixer, surface: RecordingSurface, clock: Clock
) -> None:
    flow_mixer.on_state(BUDS_ON)
    clock.now = 10
    flow_mixer.on_state(DISCONNECTED)
    assert labels(surface)[1] == "Buds"
