"""
Custom channels: a strip whose parts are bound, here to values that programs of your own set and watch.
"""

import dataclasses

from tests.support.commands import FakeCommands
from tests.support.hardware import RecordingSurface
from tests.support.strips import ID, build
from tests.support.tasks import settle
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.strips import CustomStripConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import RingMode
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.custom import CustomStrip

SET = ("brightness", "-d", "DP-1", "-b", "{value}")
WATCH = ("brightness", "-d", "DP-1", "--watch")
FADER = {"set": SET, "min": 0.1, "max": 1.0}


def config(**options: object) -> CustomStripConfig:
    return CustomStripConfig.model_validate({"type": "custom"} | options)


def ran(commands: FakeCommands) -> list[str]:
    """The values that `set` ran with."""
    return [argv[-1] for argv in commands.runs]


async def test_the_strip_shows_the_label_the_value_on_the_lcd_the_ring_and_the_fader(
    surface: RecordingSurface, env: StripEnv
) -> None:
    commands = FakeCommands()
    env = dataclasses.replace(env, commands=commands)
    fader = FADER | {"watch": WATCH, "format": "{value:.0%}"}
    strip = build(config(label="Left", fader=fader, color="cyan"), surface.strips[0], env)
    assert isinstance(strip, CustomStrip)
    assert strip.encoder_value() is None
    device = surface.strips[0]
    strip.update(AudioState())
    assert device.text == ["Left", ""]
    # nothing known: the fader stays where it is
    assert device.fader is None
    commands.print("0.55")
    await settle()
    assert device.text[1] == "55%"
    assert device.ring == (6, RingMode.WRAP)
    assert device.fader == protocol.fader_value(0.5)
    assert device.color == protocol.Color.CYAN
    # a hand on the fader: the value follows, the motor stays off until it is let go
    strip.on_touch(True)
    strip.on_fader(1.0)
    await settle()
    assert ran(commands) == ["1"]
    assert device.text[1] == "100%"
    assert device.fader == protocol.fader_value(0.5)
    strip.on_touch(False)
    assert device.fader == protocol.fader_value(1.0)
    # the encoder sets the fader's value in fine steps
    strip.on_encoder(-10)
    await settle()
    assert ran(commands)[-1] == "0.91"
    strip.on_encoder_press(True)
    await settle()
    # no push: nothing
    assert ran(commands)[-1] == "0.91"
    strip.close()
    await commands.wait_closed()


async def test_an_encoder_of_its_own_sets_its_own_value(surface: RecordingSurface, env: StripEnv) -> None:
    commands = FakeCommands()
    env = dataclasses.replace(env, commands=commands)
    encoder = {"set": ["volume", "{value}"], "push": 50, "step": 5}
    strip = build(config(encoder=encoder), surface.strips[0], env)
    assert isinstance(strip, CustomStrip)
    assert strip.fader_value() is None
    device = surface.strips[0]
    strip.update(AudioState())
    # no fader: it stays down, and the LCD shows the encoder's value
    assert device.fader == protocol.fader_value(0.0)
    strip.on_fader(0.7)
    strip.on_touch(True)
    strip.on_encoder_press(True)
    await settle()
    assert commands.runs == [["volume", "50"]]
    strip.on_encoder(1)
    await settle()
    assert commands.runs[-1] == ["volume", "55"]
    assert device.text[1] == "55"
    assert device.ring[1] == RingMode.WRAP
    strip.close()
    await commands.wait_closed()


async def test_a_strip_without_bindings_is_dark_and_named_by_its_channel(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = build(config(), surface.strips[0], dataclasses.replace(env, commands=FakeCommands()))
    strip.update(AudioState())
    strip.on_encoder(3)
    strip.on_encoder_press(True)
    device = surface.strips[0]
    assert device.text == [ID.name, ""]
    assert device.ring == (0, RingMode.DOT)
    strip.close()


async def test_the_first_target_fills_the_programs(surface: RecordingSurface, env: StripEnv) -> None:
    commands = FakeCommands()
    targets = [{"name": "Left", "value": "DP-1"}, {"name": "Right", "value": "DP-2"}]
    fader = {"set": "b -d {target} {value}"}
    strip = build(config(fader=fader, targets=targets), surface.strips[0], dataclasses.replace(env, commands=commands))
    strip.on_fader(0.5)
    await settle()
    assert commands.runs == [["b", "-d", "DP-1", "50"]]
    strip.close()
    await commands.wait_closed()
