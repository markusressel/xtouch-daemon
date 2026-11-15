import asyncio

import pytest

from tests.conftest import FakeBackend, RecordingSurface, output, settle, source, stream
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config import AppsStripConfig, AutoStripConfig, DeviceStripConfig, StripConfig
from xtouch_daemon.protocol import Color, RingMode
from xtouch_daemon.strips import build_strip
from xtouch_daemon.strips.apps import AppGroupStrip
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.device import DeviceStrip
from xtouch_daemon.strips.knobs import BalanceKnob, Knob, VolumeKnob, ring_position


def device(surface: RecordingSurface, env: StripEnv, direction: Direction = Direction.OUTPUT) -> DeviceStrip:
    name = "speaker" if direction == Direction.OUTPUT else "mic"
    return DeviceStrip(surface.strips[0], env, direction, (name,), color=Color.CYAN, encoder="balance")


def test_the_ring_goes_from_the_first_to_the_last_led():
    assert [ring_position(f) for f in (-1, 0, 0.5, 1, 2)] == [1, 1, 6, 11, 11]


async def test_the_balance_turns_from_the_center_and_a_push_centers_it(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = device(surface, env)
    strip.update(AudioState(outputs=(output("speaker", balance=0.0),)))
    s = surface.strips[0]
    assert s.ring == (6, RingMode.BOOST_CUT)

    # the ring follows right away, only the latest one is set
    backend.gate = asyncio.Event()
    strip.on_encoder(4)
    await settle()
    strip.on_encoder(6)
    strip.on_encoder(10)
    assert s.ring == (11, RingMode.BOOST_CUT)
    backend.gate.set()
    await settle()
    assert backend.calls == [
        ("set_device_balance", Direction.OUTPUT, "speaker", 0.2),
        ("set_device_balance", Direction.OUTPUT, "speaker", 1.0),
    ]

    strip.update(AudioState(outputs=(output("speaker", balance=-0.4),)))
    assert s.ring == (4, RingMode.BOOST_CUT)
    strip.on_encoder_press(False)
    strip.on_encoder_press(True)
    await settle()
    assert backend.calls[-1] == ("set_device_balance", Direction.OUTPUT, "speaker", 0.0)
    # the volume stays on the fader
    assert s.text[1] == "50%"


async def test_a_mono_device_has_no_balance(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = device(surface, env, Direction.INPUT)
    strip.update(AudioState(inputs=(source("mic", balance=None),)))
    strip.on_encoder(3)
    strip.on_encoder_press(True)
    await settle()
    assert backend.calls == []
    assert surface.strips[0].ring == (0, RingMode.DOT)


async def test_a_balance_that_fails_is_logged(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    backend.failing.add("set_device_balance")
    strip = device(surface, env)
    strip.update(AudioState(outputs=(output("speaker"),)))
    strip.on_encoder(1)
    await settle()
    assert "Strip 1: setting the balance: set_device_balance failed" in caplog.text
    # back to what the device has
    strip.update(AudioState(outputs=(output("speaker"),)))
    assert surface.strips[0].ring == (6, RingMode.BOOST_CUT)


async def test_a_missing_device_ignores_the_encoder(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = device(surface, env)
    strip.update(AudioState())
    strip.on_encoder(1)
    strip.on_encoder_press(True)
    await settle()
    assert backend.calls == []


async def test_applications_get_the_balance_of_all_their_streams(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = AppGroupStrip(surface.strips[0], env, ("brave",), "Browser", encoder="balance")
    strip.update(AudioState(streams=(stream(2, balance=0.5), stream(1, balance=-0.5))))
    # the first stream shows the balance; halves round away from the center
    assert surface.strips[0].ring == (3, RingMode.BOOST_CUT)
    strip.update(AudioState(streams=(stream(1, balance=0.5),)))
    assert surface.strips[0].ring == (9, RingMode.BOOST_CUT)

    strip.on_encoder(-2)
    await settle()
    assert backend.calls == [("set_stream_balance", 1, 0.4)]


async def test_a_strip_without_a_knob_of_that_kind_says_so(surface: RecordingSurface, env: StripEnv) -> None:
    with pytest.raises(ValueError, match="DeviceStrip has no encoder 'pick'"):
        DeviceStrip(surface.strips[0], env, Direction.OUTPUT, (), encoder="pick")  # type: ignore[arg-type]


def test_a_knob_does_nothing_by_default(surface: RecordingSurface, env: StripEnv) -> None:
    knob = Knob(DeviceStrip(surface.strips[0], env, Direction.OUTPUT, ()))
    knob.turn(1)
    knob.push(True)
    knob.close()
    assert knob.ring() == (0, RingMode.DOT)


async def test_the_volume_knob_steps_and_resets(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = DeviceStrip(surface.strips[0], env, Direction.OUTPUT, ("speaker",), encoder="volume")
    strip.update(AudioState(outputs=(output("speaker", 50),)))
    assert surface.strips[0].ring == (6, RingMode.WRAP)
    strip.on_encoder(-1)
    await settle()
    strip.on_encoder_press(True)
    strip.on_encoder_press(False)
    await settle()
    assert [call[3] for call in backend.calls] == [49, 100]


async def test_a_balance_for_a_device_that_went_away_is_dropped(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = device(surface, env)
    strip.update(AudioState(outputs=(output("speaker"),)))
    backend.gate = asyncio.Event()
    strip.on_encoder(1)
    await settle()
    strip.on_encoder(1)
    strip.update(AudioState())
    backend.gate.set()
    await settle()
    assert backend.calls == [("set_device_balance", Direction.OUTPUT, "speaker", 0.05)]


@pytest.mark.parametrize(
    ("config", "knob"),
    [
        (DeviceStripConfig(type="output"), BalanceKnob),
        (DeviceStripConfig(type="input", encoder="volume"), VolumeKnob),
        (AppsStripConfig(type="apps", match=("a",), label="A"), VolumeKnob),
        (AutoStripConfig(type="auto", encoder="balance"), BalanceKnob),
    ],
)
def test_the_encoder_of_a_strip_by_default_and_configured(
    surface: RecordingSurface, env: StripEnv, config: StripConfig, knob: type[Knob]
) -> None:
    strip = build_strip(config, surface.strips[0], env, {})
    assert type(strip.knob) is knob  # type: ignore[attr-defined]
