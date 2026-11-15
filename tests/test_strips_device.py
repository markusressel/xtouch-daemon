import asyncio

import pytest

from tests.conftest import FakeBackend, RecordingSurface, output, settle, source
from xtouch_daemon import protocol
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Direction
from xtouch_daemon.config import BehaviorConfig
from xtouch_daemon.protocol import Button, Color, Led, RingMode
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.device import DeviceStrip


def make(
    surface: RecordingSurface,
    env: StripEnv,
    direction: Direction = Direction.OUTPUT,
    device: str | None = "speaker",
    **kwargs: object,
) -> DeviceStrip:
    return DeviceStrip(surface.strips[0], env, direction, device, color=Color.CYAN, **kwargs)  # type: ignore[arg-type]


STATE = AudioState(
    outputs=(output("speaker", 50), output("buds", 30, running=True)),
    inputs=(source("mic", 80),),
    default_output="buds",
    default_input="mic",
)


async def test_the_volume_shows_on_fader_lcd_and_ring(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, label="Speaker")
    strip.update(STATE)
    await surface.settled()

    s = surface.strips[0]
    assert surface.faders(0)[-1] == protocol.fader_value(0.5)
    assert s.text == ["Speaker", "50%"]
    assert s.ring == (6, RingMode.WRAP)
    assert s.color == Color.CYAN
    assert s.leds[Button.MUTE] == Led.OFF


async def test_a_muted_device_says_so(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env)
    strip.update(AudioState(outputs=(output("speaker", 50, muted=True),)))

    assert surface.strips[0].text[1] == "muted"
    assert surface.strips[0].leds[Button.MUTE] == Led.ON


async def test_the_label_defaults_to_the_start_of_the_description(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env)
    assert strip.label == "Output"

    strip.update(STATE)
    assert surface.strips[0].text[0] == "speaker"


async def test_the_default_device_strip_follows_the_default(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device=None)
    strip.update(STATE)
    assert surface.strips[0].text == ["Output", "30%"]

    strip.update(AudioState(outputs=STATE.outputs, default_output="speaker"))
    assert surface.strips[0].text == ["Output", "50%"]
    # a default strip has nothing to select
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF


async def test_an_input_strip_is_labelled_input(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, Direction.INPUT, None)
    strip.update(STATE)
    assert surface.strips[0].text == ["Input", "80%"]


async def test_a_missing_device_is_dark_off_and_ignores_the_fader(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env, device="gone", label="Buds")
    strip.update(STATE)
    await surface.settled()

    s = surface.strips[0]
    assert s.color == Color.BLACK
    assert s.text == ["Buds", "off"]
    assert surface.faders(0)[-1] == 0
    assert s.ring == (0, RingMode.DOT)

    strip.on_fader(0.5)
    strip.on_encoder(3)
    strip.on_encoder_press(True)
    strip.on_button(Button.MUTE, True)
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls == []


async def test_without_a_sound_server_every_device_is_off(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device=None)
    strip.update(DISCONNECTED)
    assert surface.strips[0].text[1] == "off"


async def test_the_fader_sets_the_volume(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_fader(0.42)
    await settle()

    assert backend.calls == [("set_device_volume", Direction.OUTPUT, "speaker", 42)]
    assert surface.strips[0].text[1] == "42%"


async def test_fast_fader_moves_set_only_the_latest_volume(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    gate = backend.gate = asyncio.Event()

    strip.on_fader(0.10)
    await settle()
    strip.on_fader(0.20)
    strip.on_fader(0.30)
    gate.set()
    await settle()

    assert [call[3] for call in backend.calls] == [10, 30]


async def test_the_volume_set_stays_shown_until_the_sound_server_reports_it(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_fader(0.7)
    await settle()

    assert surface.strips[0].text[1] == "70%"


async def test_a_failing_volume_command_is_logged(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    backend.failing.add("set_device_volume")

    strip.on_fader(0.7)
    await settle()

    assert "set_device_volume failed" in caplog.text
    # the strip shows the volume it knows again
    assert surface.strips[0].text[1] == "50%"


async def test_the_encoder_changes_the_volume_in_steps_and_moves_the_fader(
    surface: RecordingSurface, backend: FakeBackend
) -> None:
    env = StripEnv(backend, BehaviorConfig(encoder_step=2))
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_encoder(3)
    await settle()
    strip.on_encoder(-1)
    await settle()
    await surface.settled()

    assert [call[3] for call in backend.calls] == [56, 54]
    assert surface.faders(0)[-1] == protocol.fader_value(0.54)


async def test_the_encoder_does_not_go_beyond_the_limits(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(AudioState(outputs=(output("speaker", 99),)))

    strip.on_encoder(5)
    await settle()

    assert backend.calls[-1][3] == 100


async def test_a_push_on_the_encoder_resets_the_volume(surface: RecordingSurface, backend: FakeBackend) -> None:
    env = StripEnv(backend, BehaviorConfig(reset_volume=80))
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_encoder_press(False)
    strip.on_encoder_press(True)
    await settle()

    assert backend.calls == [("set_device_volume", Direction.OUTPUT, "speaker", 80)]


async def test_above_100_percent_the_fader_covers_the_amplification(
    surface: RecordingSurface, backend: FakeBackend
) -> None:
    env = StripEnv(backend, BehaviorConfig(max_volume=150))
    strip = make(surface, env)
    strip.update(AudioState(outputs=(output("speaker", 150),)))
    await surface.settled()
    assert surface.faders(0)[-1] == protocol.FADER_MAX

    strip.on_fader(0.5)
    await settle()
    assert backend.calls[-1][3] == 75


async def test_mute_toggles_mute(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_button(Button.MUTE, True)
    strip.on_button(Button.MUTE, False)
    await settle()
    strip.update(AudioState(outputs=(output("speaker", 50, muted=True),)))
    strip.on_button(Button.MUTE, True)
    await settle()

    assert backend.calls == [
        ("set_device_mute", Direction.OUTPUT, "speaker", True),
        ("set_device_mute", Direction.OUTPUT, "speaker", False),
    ]


async def test_select_makes_the_device_the_default_and_its_led_shows_it(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF

    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls == [("set_default", Direction.OUTPUT, "speaker")]

    strip.update(AudioState(outputs=STATE.outputs, default_output="speaker"))
    assert surface.strips[0].leds[Button.SELECT] == Led.ON


async def test_select_can_be_switched_off(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env, select=False)
    strip.update(AudioState(outputs=STATE.outputs, default_output="speaker"))

    strip.on_button(Button.SELECT, True)
    await settle()

    assert backend.calls == []
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF


async def test_a_failing_command_is_logged(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    backend.failing.add("set_default")

    strip.on_button(Button.SELECT, True)
    await settle()

    assert "Strip 1: make default: set_default failed" in caplog.text


async def test_the_meter_shows_the_monitor_of_an_output_or_the_input(surface: RecordingSurface, env: StripEnv) -> None:
    out = make(surface, env)
    mic = make(surface, env, Direction.INPUT, "mic")

    assert out.meter_targets(STATE) == {CaptureTarget("speaker", monitor=True)}
    assert mic.meter_targets(STATE) == {CaptureTarget("mic", monitor=False)}
    assert make(surface, env, device="gone").meter_targets(STATE) == set()
    assert make(surface, env, meter=False).meter_targets(STATE) == set()


async def test_the_meters_can_be_switched_off_for_all_strips(surface: RecordingSurface, backend: FakeBackend) -> None:
    env = StripEnv(backend, BehaviorConfig(meters=False))
    assert make(surface, env).meter_targets(STATE) == set()


async def test_a_device_plays_while_it_runs(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device="buds")

    assert strip.is_playing(CaptureTarget("buds", True), STATE)
    assert not strip.is_playing(CaptureTarget("speaker", True), STATE)
    assert not strip.is_playing(CaptureTarget("gone", True), STATE)


async def test_closing_stops_running_commands(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    backend.gate = asyncio.Event()
    strip.on_button(Button.MUTE, True)
    await settle()

    strip.close()
    await settle()

    assert all(task.done() for task in strip._tasks)


async def test_a_device_that_went_away_gets_no_queued_volume(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    gate = backend.gate = asyncio.Event()
    strip.on_fader(0.1)
    await settle()
    strip.on_fader(0.2)
    # the set volume shows while the command runs, even when a state comes in between
    strip.update(STATE)
    assert surface.strips[0].text[1] == "20%"

    strip.update(AudioState())
    gate.set()
    await settle()

    assert backend.calls == [("set_device_volume", Direction.OUTPUT, "speaker", 10)]


async def test_a_device_that_went_away_gets_no_mute(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_button(Button.MUTE, True)
    strip.update(AudioState())
    await settle()

    assert backend.calls == []


REC_SOLO = {Button.REC: "recording", Button.SOLO: "playing"}


async def test_the_rec_led_shows_whether_an_application_records_the_device(
    surface: RecordingSurface, env: StripEnv
) -> None:
    from xtouch_daemon.audio.model import Capture

    mic = make(surface, env, Direction.INPUT, "mic", indicators=REC_SOLO)
    discord = Capture(5, "Discord", "discord", "mic", Direction.INPUT, corked=False)

    mic.update(AudioState(inputs=STATE.inputs, captures=(discord,)))
    assert surface.strips[0].leds[Button.REC] == Led.ON

    mic.update(AudioState(inputs=STATE.inputs))
    assert surface.strips[0].leds[Button.REC] == Led.OFF


@pytest.mark.parametrize(
    ("indicator", "device", "lit"),
    [
        ("playing", "buds", True),
        ("playing", "speaker", False),
        ("default", "buds", True),
        ("default", "speaker", False),
        ("muted", "speaker", False),
        ("off", "buds", False),
        ("recording", "buds", False),
        # a device that is not there shows nothing
        ("playing", "gone", False),
        ("default", "gone", False),
        ("muted", "gone", False),
    ],
)
async def test_leds_show_what_they_are_set_to(
    surface: RecordingSurface, env: StripEnv, indicator: str, device: str, lit: bool
) -> None:
    strip = make(surface, env, device=device, indicators={Button.SOLO: indicator})
    strip.update(STATE)

    assert surface.strips[0].leds[Button.SOLO] == (Led.ON if lit else Led.OFF)


async def test_the_muted_indicator(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, indicators={Button.SOLO: "muted"})
    strip.update(AudioState(outputs=(output("speaker", 50, muted=True),)))

    assert surface.strips[0].leds[Button.SOLO] == Led.ON


async def test_leds_without_indicator_are_left_alone(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    assert Button.REC not in surface.strips[0].leds
