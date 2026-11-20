"""
Command channels: the value that programs of your own set and watch, and the strip that shows it.
"""

import asyncio
import dataclasses
import logging

import pytest
from pydantic import ValidationError

from tests.support.commands import END, FakeCommands
from tests.support.hardware import RecordingSurface
from tests.support.strips import ID, build
from tests.support.tasks import settle
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.strips import CommandStripConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import RingMode
from xtouch_daemon.strips import command as command_module
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.command import CommandStrip, CommandValue, parse_value, value_text
from xtouch_daemon.strips.knobs import ring_position

SET = ("brightness", "-d", "DP-1", "-b", "{value}")
WATCH = ("brightness", "-d", "DP-1", "--watch")


def config(**options: object) -> CommandStripConfig:
    return CommandStripConfig.model_validate({"type": "command", "set": SET, "min": 0.1, "max": 1.0} | options)


def value(commands: FakeCommands, changes: list[None] | None = None, **options: object) -> CommandValue:
    result = CommandValue(config(**options), commands, 1, "screen")
    if changes is not None:
        result.listeners.append(lambda: changes.append(None))
    return result


def ran(commands: FakeCommands) -> list[str]:
    """The values that `set` ran with."""
    return [argv[-1] for argv in commands.runs]


def test_a_value_is_given_without_an_exponent_and_trailing_zeros():
    assert [value_text(v) for v in (0.6, 0.1 + 0.2, 42.0, 1e-7, 1234567.0, -0.5)] == [
        "0.6",
        "0.3",
        "42",
        "0",
        "1234567",
        "-0.5",
    ]


def test_the_first_number_of_a_line_is_the_value():
    assert [parse_value(line) for line in ("0.60", "brightness: 42 %", "-3", "dark", "")] == [0.6, 42, -3, None, None]


@pytest.mark.parametrize(
    ("options", "problem"),
    [
        ({"set": ["brightness", "-b", "1"]}, "set: no argument has {value}"),
        ({"set": ["{value}"]}, "set: no argument has {value}"),
        ({"min": 1.0, "max": 0.1}, "min: 1 is not below max (0.1)"),
        ({"step": 0}, "step: needs to be above 0"),
        ({"push": 2.0}, "push: 2 is not between min (0.1) and max (1)"),
        ({"format": "{value:d}"}, "format: {value:d} can't show a value"),
        ({"format": "{level}"}, "format: {level} can't show a value"),
    ],
)
def test_a_command_channel_needs_a_value_a_range_and_a_step(options: dict[str, object], problem: str) -> None:
    with pytest.raises(ValidationError) as error:
        config(**options)
    assert problem in str(error.value)


async def test_a_turn_sets_the_value_by_a_step_of_the_encoder_step_of_the_range() -> None:
    commands = FakeCommands()
    knob = value(commands, push=1.0)
    # nothing known yet: the ring is dark, the LCD empty, a turn starts from push
    assert knob.ring() == (0, RingMode.DOT)
    assert knob.text() == ""
    knob.turn(-2)
    await settle()
    # 1 % of 0.9 per step
    assert commands.runs == [["brightness", "-d", "DP-1", "-b", "0.982"]]
    assert knob.ring() == (ring_position((0.982 - 0.1) / 0.9), RingMode.WRAP)
    knob.turn(-100)
    await settle()
    # not below the range
    assert ran(commands)[-1] == "0.1"
    assert knob.ring() == (1, RingMode.WRAP)
    knob.close()


async def test_a_turn_without_push_starts_from_min() -> None:
    commands = FakeCommands()
    knob = value(commands, step=0.05)
    knob.turn(2)
    await settle()
    assert ran(commands) == ["0.2"]
    knob.close()


async def test_a_push_sets_push_and_without_it_does_nothing() -> None:
    commands = FakeCommands()
    knob = value(commands, push=1.0)
    knob.push(True)
    knob.push(False)
    await settle()
    assert ran(commands) == ["1"]
    plain = value(commands)
    plain.push(True)
    await settle()
    assert ran(commands) == ["1"]
    knob.close()
    plain.close()


async def test_turns_faster_than_the_program_set_only_the_newest_value() -> None:
    commands = FakeCommands()
    commands.run_time = 0.1
    changes: list[None] = []
    knob = value(commands, changes, step=0.1, push=0.5)
    knob.turn(1)
    await settle()
    for _ in range(3):
        knob.turn(1)
    # every turn shows at once
    assert knob.value == 0.9
    assert len(changes) == 4
    await asyncio.sleep(0.5)
    # the first turn runs, the others wait for it: only the last of them runs after it
    assert ran(commands) == ["0.6", "0.9"]
    knob.close()


async def test_a_failing_program_is_logged_and_the_next_value_runs(caplog: pytest.LogCaptureFixture) -> None:
    commands = FakeCommands()
    commands.failing = "brightness failed (1): no display DP-1"
    knob = value(commands, step=0.1)
    with caplog.at_level(logging.WARNING):
        knob.turn(1)
        await settle()
    assert "screen: setting 0.2: brightness failed (1): no display DP-1" in caplog.text
    commands.failing = None
    knob.turn(1)
    await settle()
    assert ran(commands) == ["0.2", "0.3"]
    knob.close()


async def test_a_fader_sets_the_range_from_min_to_max() -> None:
    commands = FakeCommands()
    fader = value(commands)
    fader.moved(0.5)
    await settle()
    assert ran(commands) == ["0.55"]
    fader.moved(0.250015)
    await settle()
    # no noise of the fader's resolution
    assert ran(commands)[-1] == "0.325"
    fader.close()


async def test_watch_tells_the_value() -> None:
    commands = FakeCommands()
    changes: list[None] = []
    knob = value(commands, changes, watch=WATCH, format="{value:.0%}")
    await settle()
    assert commands.watches == [list(WATCH)]
    commands.print("0.60")
    await settle()
    assert knob.value == 0.6
    assert knob.text() == "60%"
    assert changes == [None]
    # the same again, or no number: nothing changed
    commands.print("0.6")
    commands.print("display off")
    await settle()
    assert changes == [None]
    # under the finger the hand knows better
    knob.touched = True
    commands.print("0.8")
    await settle()
    assert knob.value == 0.6
    knob.touched = False
    # and while a value is set
    commands.run_time = 1.0
    knob.turn(1)
    commands.print("0.1")
    await settle()
    assert knob.value == 0.609
    knob.close()


async def test_a_watch_that_ends_or_cant_start_runs_again(caplog: pytest.LogCaptureFixture) -> None:
    commands = FakeCommands()
    commands.unstartable = True
    with caplog.at_level(logging.WARNING):
        knob = value(commands, watch=WATCH)
        await settle()
        assert "screen: watch: can't start brightness: No such file or directory, again in 5 s" in caplog.text
        commands.unstartable = False
        await asyncio.sleep(command_module.WATCH_RESTART)
        assert len(commands.watches) == 2
        commands.print(END)
        await settle()
        assert "screen: brightness (watch) ended, again in 5 s" in caplog.text
        await asyncio.sleep(command_module.WATCH_RESTART)
        assert len(commands.watches) == 3
    knob.close()
    await commands.wait_closed()


async def test_a_simulated_value_starts_in_the_middle() -> None:
    commands = FakeCommands()
    commands.simulated = True
    knob = value(commands)
    assert knob.value == 0.55
    knob.close()


async def test_the_strip_shows_the_label_the_value_on_the_lcd_the_ring_and_the_fader(
    surface: RecordingSurface, env: StripEnv
) -> None:
    commands = FakeCommands()
    env = dataclasses.replace(env, commands=commands)
    strip = build(config(label="Left", watch=WATCH, format="{value:.0%}", color="cyan"), surface.strips[0], env)
    assert isinstance(strip, CommandStrip)
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
    strip.on_encoder(-10)
    await settle()
    assert ran(commands)[-1] == "0.91"
    strip.on_encoder_press(True)
    await settle()
    # no push: nothing
    assert ran(commands)[-1] == "0.91"
    strip.close()
    await commands.wait_closed()


async def test_the_strip_is_named_by_its_channel_without_a_label(surface: RecordingSurface, env: StripEnv) -> None:
    strip = build(config(), surface.strips[0], dataclasses.replace(env, commands=FakeCommands()))
    strip.update(AudioState())
    assert surface.strips[0].text[0] == ID.name
    strip.close()
