"""
The values, watches and programs of bindings: a value that programs of your own set and watch, the newest line of a
watch, a program a button runs, and how lines become values, LEDs, colors and levels.
"""

import asyncio
import logging

import pytest

from tests.support.commands import END, FakeCommands
from tests.support.tasks import settle
from xtouch_daemon.config.bindings import ValueBinding
from xtouch_daemon.hardware.protocol import Led, RingMode
from xtouch_daemon.strips import value as value_module
from xtouch_daemon.strips.knobs import ring_position
from xtouch_daemon.strips.value import (
    CommandValue,
    WatchedLine,
    color_of_line,
    led_of_line,
    level_of_line,
    parse_value,
    run_program,
    value_text,
)

SET = ("brightness", "-d", "DP-1", "-b", "{value}")
WATCH = ("brightness", "-d", "DP-1", "--watch")


def binding(**options: object) -> ValueBinding:
    return ValueBinding.model_validate({"set": SET, "min": 0.1, "max": 1.0} | options)


def value(commands: FakeCommands, changes: list[None] | None = None, **options: object) -> CommandValue:
    result = CommandValue(binding(**options), commands, 1, "screen")
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


async def test_a_value_stays_touched_while_any_finger_is_on_a_fader_of_it() -> None:
    commands = FakeCommands()
    knob = value(commands)
    # two slots show the value: one finger lets go, the other still holds it
    knob.touch(True)
    knob.touch(True)
    knob.touch(False)
    assert knob.touched
    knob.touch(False)
    assert not knob.touched
    # a release without a touch (e.g. at the start) leaves it free
    knob.touch(False)
    knob.touch(True)
    assert knob.touched
    knob.close()


async def test_a_watch_that_ends_or_cant_start_runs_again(caplog: pytest.LogCaptureFixture) -> None:
    commands = FakeCommands()
    commands.unstartable = True
    with caplog.at_level(logging.WARNING):
        knob = value(commands, watch=WATCH)
        await settle()
        assert "screen: watch: can't start brightness: No such file or directory, again in 5 s" in caplog.text
        commands.unstartable = False
        await asyncio.sleep(value_module.WATCH_RESTART)
        assert len(commands.watches) == 2
        commands.print(END)
        await settle()
        assert "screen: brightness (watch) ended, again in 5 s" in caplog.text
        await asyncio.sleep(value_module.WATCH_RESTART)
        assert len(commands.watches) == 3
    knob.close()
    await commands.wait_closed()


async def test_a_simulated_value_starts_in_the_middle() -> None:
    commands = FakeCommands()
    commands.simulated = True
    knob = value(commands)
    assert knob.value == 0.55
    knob.close()


async def test_placeholders_fill_the_programs() -> None:
    commands = FakeCommands()
    knob = CommandValue(
        ValueBinding.model_validate({"set": "b -d {target} {value}", "watch": "b -d {target} -w"}),
        commands,
        1,
        "screen",
        {"target": "DP-2"},
    )
    await settle()
    assert commands.watches == [["b", "-d", "DP-2", "-w"]]
    knob.set(42)
    await settle()
    assert commands.runs == [["b", "-d", "DP-2", "42"]]
    knob.close()


def test_a_line_lights_an_led_flashes_it_or_turns_it_off():
    lines = ("on", " ON ", "1", "true", "Yes", "flash", "off", "0", "", "lit")
    assert [led_of_line(line) for line in lines] == [Led.ON] * 5 + [Led.FLASH] + [Led.OFF] * 4


def test_a_line_names_a_color():
    assert [color_of_line(line) for line in ("red", " Cyan\n", "off", "pink", "")] == ["red", "cyan", "off", None, None]


def test_a_line_is_a_level_between_min_and_max():
    lines = ("50", "load: 75 %", "-10", "250", "idle")
    assert [level_of_line(line, 0, 100) for line in lines] == [0.5, 0.75, 0.0, 1.0, None]
    assert level_of_line("0.55", 0.1, 1.0) == pytest.approx(0.5)


async def test_a_watched_line_is_the_newest_and_tells_its_listeners() -> None:
    commands = FakeCommands()
    changes: list[str | None] = []
    watched = WatchedLine(["playerctl", "status", "--follow"], commands, "music.lcd")
    watched.listeners.append(lambda: changes.append(watched.line))
    assert watched.line is None
    await settle()
    assert commands.watches == [["playerctl", "status", "--follow"]]
    commands.print("Playing")
    commands.print("Playing")
    commands.print("Paused")
    await settle()
    assert changes == ["Playing", "Paused"]
    watched.close()
    await commands.wait_closed()


async def test_a_watched_line_runs_again_after_its_program_ended(caplog: pytest.LogCaptureFixture) -> None:
    commands = FakeCommands()
    with caplog.at_level(logging.WARNING):
        watched = WatchedLine(["status"], commands, "music.lcd")
        await settle()
        commands.print("Playing")
        commands.print(END)
        await settle()
        assert "music.lcd: status (watch) ended, again in 5 s" in caplog.text
        await asyncio.sleep(value_module.WATCH_RESTART)
        assert len(commands.watches) == 2
    # the line stays until the next one
    assert watched.line == "Playing"
    watched.close()
    await commands.wait_closed()


async def test_a_program_runs_to_its_end_and_its_problems_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    commands = FakeCommands()
    run_program(commands, ["reset", "-d", "DP-1"], "screen.select")
    await commands.wait_closed()
    assert commands.runs == [["reset", "-d", "DP-1"]]
    commands.failing = "reset failed (1): no display"
    with caplog.at_level(logging.WARNING):
        run_program(commands, ["reset"], "screen.select")
        await commands.wait_closed()
    assert "screen.select: reset failed (1): no display" in caplog.text
