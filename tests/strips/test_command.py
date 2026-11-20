"""
A fader or an encoder that sets a value with a program of your own: what runs, what the ring and the fader show, and
what a `watch` tells.
"""

import asyncio
import logging

import pytest

from tests.support.commands import END, FakeCommands
from tests.support.hardware import RecordingSurface
from tests.support.tasks import settle
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import RingMode
from xtouch_daemon.slots.model import CommandControl
from xtouch_daemon.strips import command as command_module
from xtouch_daemon.strips.command import CommandLink, parse_value, value_text
from xtouch_daemon.strips.knobs import ring_position

SET = ("brightness", "-d", "DP-1", "-b", "{value}")
WATCH = ("brightness", "-d", "DP-1", "--watch")


def link(
    surface: RecordingSurface,
    commands: FakeCommands,
    changes: list[None] | None = None,
    **options: object,
) -> CommandLink:
    config = CommandControl.model_validate({"set": SET, "range": (0.1, 1.0)} | options)
    on_change = (lambda: changes.append(None)) if changes is not None else lambda: None
    return CommandLink(surface.strips[0], config, commands, 1, "controls.1.encoder", on_change)


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
        ({"set": ["brightness", "-b", "1"]}, "no argument has {value}"),
        ({"set": ["{value}"]}, "no argument has {value}"),
        ({"range": (1.0, 0.1)}, "range: 1 is not below 0.1"),
        ({"step": 0}, "step: needs to be above 0"),
        ({"push": 2.0}, "push: 2 is outside of range (0.1 to 1)"),
    ],
)
def test_a_command_needs_a_value_a_range_and_a_step(options: dict[str, object], problem: str) -> None:
    with pytest.raises(ValueError, match=problem.replace("(", r"\(").replace(")", r"\)").replace("{", r"\{")):
        CommandControl.model_validate({"set": SET, "range": (0.1, 1.0)} | options)


async def test_a_turn_sets_the_value_by_a_step_of_the_encoder_step_of_the_range(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    knob = link(surface, commands, push=1.0)
    # nothing known yet: the ring is dark, a turn starts from push
    assert knob.ring() == (0, RingMode.DOT)
    knob.turn(-2)
    await settle()
    # 1 % of 0.9 per step
    assert commands.runs == [["brightness", "-d", "DP-1", "-b", "0.982"]]
    assert surface.strips[0].ring == (ring_position((0.982 - 0.1) / 0.9), RingMode.WRAP)
    knob.turn(-100)
    await settle()
    # not below the range
    assert ran(commands)[-1] == "0.1"
    assert surface.strips[0].ring == (1, RingMode.WRAP)
    knob.close()


async def test_a_turn_without_push_starts_from_the_bottom(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    knob = link(surface, commands, step=0.05)
    knob.turn(2)
    await settle()
    assert ran(commands) == ["0.2"]
    knob.close()


async def test_a_push_sets_push_and_without_it_does_nothing(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    knob = link(surface, commands, push=1.0)
    knob.push(True)
    knob.push(False)
    await settle()
    assert ran(commands) == ["1"]
    assert surface.strips[0].ring == (11, RingMode.WRAP)
    plain = link(surface, commands)
    plain.push(True)
    await settle()
    assert ran(commands) == ["1"]
    knob.close()
    plain.close()


async def test_turns_faster_than_the_program_set_only_the_newest_value(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    commands.run_time = 0.1
    knob = link(surface, commands, step=0.1, push=0.5)
    knob.turn(1)
    await settle()
    for _ in range(3):
        knob.turn(1)
    # the ring follows every turn at once
    assert knob.value == 0.9
    await asyncio.sleep(0.5)
    # the first turn runs, the others wait for it: only the last of them runs after it
    assert ran(commands) == ["0.6", "0.9"]
    knob.close()


async def test_a_failing_program_is_logged_and_the_next_value_runs(
    surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    commands = FakeCommands()
    commands.failing = "brightness failed (1): no display DP-1"
    knob = link(surface, commands, step=0.1)
    with caplog.at_level(logging.WARNING):
        knob.turn(1)
        await settle()
    assert "controls.1.encoder: setting 0.2: brightness failed (1): no display DP-1" in caplog.text
    commands.failing = None
    knob.turn(1)
    await settle()
    assert ran(commands) == ["0.2", "0.3"]
    knob.close()


async def test_the_fader_sets_the_range_from_the_bottom_to_the_top(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    fader = link(surface, commands)
    # nothing known: the fader stays where it is
    fader.show_fader()
    assert surface.strips[0].fader is None
    fader.touch(True)
    fader.moved(0.5)
    await settle()
    assert ran(commands) == ["0.55"]
    # under the finger the motor stays off
    assert surface.strips[0].fader is None
    fader.touch(False)
    assert surface.strips[0].fader == protocol.fader_value(0.5)
    fader.close()


async def test_watch_tells_the_value_and_the_strip_follows(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    changes: list[None] = []
    knob = link(surface, commands, changes, watch=WATCH)
    await settle()
    assert commands.watches == [list(WATCH)]
    commands.print("0.60")
    await settle()
    assert knob.value == 0.6
    assert changes == [None]
    # the same again, or no number: nothing changed
    commands.print("0.6")
    commands.print("display off")
    await settle()
    assert changes == [None]
    knob.show_fader()
    assert surface.strips[0].fader == protocol.fader_value(0.5 / 0.9)
    # under the finger the hand knows better
    knob.touch(True)
    commands.print("0.8")
    await settle()
    assert knob.value == 0.6
    knob.touch(False)
    # and while a value is set
    commands.run_time = 1.0
    knob.turn(1)
    commands.print("0.1")
    await settle()
    assert knob.value == 0.609
    knob.close()


async def test_a_watch_that_ends_or_cant_start_runs_again(
    surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    commands = FakeCommands()
    commands.unstartable = True
    with caplog.at_level(logging.WARNING):
        knob = link(surface, commands, watch=WATCH)
        await settle()
        assert "controls.1.encoder: watch: can't start brightness: No such file or directory, again in 5 s" in (
            caplog.text
        )
        commands.unstartable = False
        await asyncio.sleep(command_module.WATCH_RESTART)
        assert len(commands.watches) == 2
        commands.print(END)
        await settle()
        assert "controls.1.encoder: brightness (watch) ended, again in 5 s" in caplog.text
        await asyncio.sleep(command_module.WATCH_RESTART)
        assert len(commands.watches) == 3
    knob.close()
    await commands.wait_closed()
