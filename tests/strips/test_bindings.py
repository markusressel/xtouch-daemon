"""
Bound parts of the audio strips (output, input, apps, auto): a fader or an encoder bound to a value of programs of your
own, and the LCD, the color, the meter and the LEDs that show what a `watch` prints; buttons that run a program.
"""

import asyncio
import logging

import pytest

from tests.support.audio import FakeBackend, output, stream
from tests.support.commands import END, FakeCommands
from tests.support.hardware import RecordingSurface
from tests.support.slots import Rig
from tests.support.strips import build, strips_of
from tests.support.tasks import settle
from tests.support.watches import ProgramCommands
from xtouch_daemon.audio.meter import CaptureTarget, Lit
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.strips import look_of
from xtouch_daemon.strips.apps import AutoStrip
from xtouch_daemon.strips.base import NOTICE_TIME, StripEnv, VolumeStrip
from xtouch_daemon.strips.bound import Parts
from xtouch_daemon.strips.knobs import CommandKnob, ring_position

SET = "brightness -d DP-1 -b {value}"
WATCH = "brightness -d DP-1 --watch"
SPEAKER = AudioState(outputs=(output("speaker", 50),))
GONE = AudioState()


@pytest.fixture
def programs() -> ProgramCommands:
    return ProgramCommands()


@pytest.fixture
def env(backend: FakeBackend, programs: ProgramCommands) -> StripEnv:
    return StripEnv(backend, BehaviorConfig(max_volume=100, encoder_step=5), commands=programs)


OUTPUT = 'type = "output"\ndevice = "speaker"'


def strip_of(surface: RecordingSurface, env: StripEnv, options: str, kind: str = OUTPUT) -> VolumeStrip:
    """The strip of the channel `it` (an output, or of `kind`) with `options`."""
    label = "" if "auto" in kind else 'label = "It"'
    (config,) = strips_of(f"[channel.it]\n{kind}\n{label}\n{options}")
    controller = build(config, surface.strips[0], env, {}, "it")
    assert isinstance(controller, VolumeStrip)
    return controller


def ran(programs: FakeCommands) -> list[str]:
    return [" ".join(argv) for argv in programs.runs]


async def test_a_strip_without_bindings_binds_nothing(surface: RecordingSurface, env: StripEnv) -> None:
    (config,) = strips_of('[channel.it]\ntype = "output"\ndevice = "speaker"\nmeter = false\ncolor = "red"')
    assert look_of(config).parts == Parts()
    strip = strip_of(surface, env, "")
    strip.update(SPEAKER)
    assert strip.bound.lines == {}
    assert strip.bound.fader is None
    assert strip.bound.encoder is None
    assert strip.held_meter("pre_fader") is None
    assert strip.value_for_run() == 50
    strip.close()


# -- the fader ------------------------------------------------------------------------------------------------------

FADER = f'fader = {{ set = "{SET}", watch = "{WATCH}", min = 0.1, max = 1.0, format = "{{value:.0%}}" }}'


async def test_a_fader_bound_to_a_program_sets_and_shows_its_value(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands, backend: FakeBackend
) -> None:
    strip = strip_of(surface, env, FADER)
    strip.update(SPEAKER)
    await settle()
    s = surface.strips[0]
    # not known yet: the fader is down, the LCD shows the volume
    assert s.fader == 0
    assert s.text == ["It", "50%"]
    programs.print_to(WATCH, "0.55")
    await settle()
    assert s.fader == protocol.fader_value(0.5)
    # a move sets the value, and the LCD shows it for a moment
    strip.on_touch(True)
    strip.on_fader(1.0)
    await settle()
    assert ran(programs) == ["brightness -d DP-1 -b 1"]
    assert s.text[1] == "100%"
    # under the finger, the watch does not move the motor
    programs.print_to(WATCH, "0.1")
    await settle()
    assert s.fader == protocol.fader_value(0.5)
    strip.on_touch(False)
    await asyncio.sleep(NOTICE_TIME)
    assert s.text[1] == "50%"
    programs.print_to(WATCH, "0.1")
    await settle()
    assert s.fader == 0
    # the encoder sets the volume, the fader stays
    strip.on_encoder(2)
    await settle()
    assert backend.calls == [("set_device_volume", strip.direction, "speaker", 60)]  # type: ignore[attr-defined]
    assert s.fader == 0
    strip.close()


async def test_a_bound_fader_works_while_the_strip_is_idle(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, FADER)
    strip.update(GONE)
    programs.print_to(WATCH, "1.0")
    await settle()
    s = surface.strips[0]
    assert s.fader == protocol.fader_value(1.0)
    strip.on_fader(0.0)
    await settle()
    assert ran(programs) == ["brightness -d DP-1 -b 0.1"]
    assert s.text == ["It", "10%"]
    await asyncio.sleep(NOTICE_TIME)
    assert s.text == ["It", "off"]
    # let go: it stays where the hand left it
    strip.on_touch(True)
    strip.on_touch(False)
    assert s.fader == 0
    strip.close()


# -- the encoder ----------------------------------------------------------------------------------------------------

ENCODER = f'encoder = {{ set = "{SET}", watch = "{WATCH}", min = 0, max = 1, step = 0.1, push = 1 }}'


async def test_an_encoder_bound_to_a_program_turns_its_value(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands, backend: FakeBackend
) -> None:
    strip = strip_of(surface, env, ENCODER)
    assert isinstance(strip.knob, CommandKnob)
    strip.update(SPEAKER)
    s = surface.strips[0]
    assert s.ring == (0, RingMode.DOT)
    programs.print_to(WATCH, "0.5")
    await settle()
    assert s.ring == (ring_position(0.5), RingMode.WRAP)
    strip.on_encoder(2)
    await settle()
    assert ran(programs) == ["brightness -d DP-1 -b 0.7"]
    assert s.text[1] == "0.7"
    assert s.ring == (ring_position(0.7), RingMode.WRAP)
    strip.on_encoder_press(True)
    strip.on_encoder_press(False)
    await settle()
    assert ran(programs)[-1] == "brightness -d DP-1 -b 1"
    assert s.text[1] == "1"
    # the fader still sets the volume
    strip.on_fader(0.3)
    await settle()
    assert backend.calls[-1][-1] == 30
    # and while the strip is idle, the encoder still sets the value
    strip.update(GONE)
    assert s.ring == (ring_position(1.0), RingMode.WRAP)
    strip.on_encoder(-1)
    await settle()
    assert ran(programs)[-1] == "brightness -d DP-1 -b 0.9"
    strip.close()


async def test_an_encoder_without_push_does_nothing_on_a_push(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'encoder = {{ set = "{SET}" }}')
    strip.update(SPEAKER)
    strip.on_encoder_press(True)
    await settle()
    assert programs.runs == []
    assert surface.strips[0].text[1] == "50%"
    strip.close()


async def test_a_taken_fader_gives_the_encoder_to_the_volume(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, ENCODER)
    strip.set_taken(frozenset({"fader"}))
    assert not isinstance(strip.knob, CommandKnob)
    strip.set_taken(frozenset())
    assert isinstance(strip.knob, CommandKnob)
    strip.close()


# -- the LCD, the color, the meter ----------------------------------------------------------------------------------

STATUS = "playerctl status --follow"


async def test_the_lcd_shows_what_its_watch_prints(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'lcd = {{ watch = "{STATUS}" }}\nencoder = "balance"')
    strip.update(AudioState(outputs=(output("speaker", 50, balance=0.0),)))
    s = surface.strips[0]
    # nothing printed yet
    assert s.text == ["It", ""]
    programs.print_to(STATUS, "Playing")
    await settle()
    assert s.text == ["It", "Playing"]
    # a notice wins while it lasts
    strip.on_encoder(1)
    assert s.text[1] == "R 5%"
    await asyncio.sleep(NOTICE_TIME)
    assert s.text[1] == "Playing"
    # so does the volume while it is set
    strip.on_fader(0.2)
    assert s.text[1] == "20%"
    await settle()
    assert s.text[1] == "Playing"
    # also while the strip is idle
    strip.update(GONE)
    programs.print_to(STATUS, "Paused")
    await settle()
    assert s.text == ["It", "Paused"]
    strip.close()


COLOR = "light-color --watch"


async def test_the_color_is_what_its_watch_names(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'color = {{ watch = "{COLOR}" }}')
    strip.update(SPEAKER)
    s = surface.strips[0]
    assert s.color == Color.WHITE
    programs.print_to(COLOR, "Red")
    await settle()
    assert s.color == Color.RED
    # a line that is no color keeps the color
    programs.print_to(COLOR, "purple-ish")
    await settle()
    assert s.color == Color.RED
    programs.print_to(COLOR, "blue")
    await settle()
    assert s.color == Color.BLUE
    # idle, it goes dark as ever
    strip.update(GONE)
    assert s.color == Color.BLACK
    strip.close()


async def test_a_watched_color_stays_lit_when_idle_if_asked(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'color = {{ watch = "{COLOR}" }}\nlit_when_idle = true')
    strip.update(GONE)
    programs.print_to(COLOR, "green")
    await settle()
    assert surface.strips[0].color == Color.GREEN
    strip.close()


LOAD = "cpu-load --watch"


async def test_the_meter_shows_the_level_its_watch_prints(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'meter = {{ watch = "{LOAD}", min = 0, max = 200 }}')
    strip.update(SPEAKER)
    # no audio meter: nothing is captured
    assert strip.meter_targets(SPEAKER) == set()
    assert strip.held_meter("pre_fader") is None
    programs.print_to(LOAD, "load: 100")
    await settle()
    assert strip.held_meter("pre_fader") == Lit(round(0.5 * protocol.METER_MAX))
    programs.print_to(LOAD, "400")
    await settle()
    assert strip.held_meter("post_fader") == Lit(protocol.METER_MAX)
    # a line without a number: nothing to show
    programs.print_to(LOAD, "busy")
    await settle()
    assert strip.held_meter("pre_fader") is None
    # idle too
    strip.update(GONE)
    programs.print_to(LOAD, "0")
    await settle()
    assert strip.held_meter("pre_fader") == Lit(0)
    strip.close()


async def test_a_meter_that_is_off_shows_nothing(surface: RecordingSurface, env: StripEnv) -> None:
    strip = strip_of(surface, env, "meter = false")
    strip.update(SPEAKER)
    assert strip.meter_targets(SPEAKER) == set()
    assert strip.held_meter("pre_fader") is None
    strip.close()


async def test_an_apps_strip_with_a_bound_meter_captures_nothing(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'meter = {{ watch = "{LOAD}" }}', kind='type = "apps"\nmatch = ["brave"]')
    state = AudioState(streams=(stream(1),))
    strip.update(state)
    assert strip.meter_targets(state) == set()
    plain = strip_of(surface, env, "", kind='type = "apps"\nmatch = ["brave"]')
    assert plain.meter_targets(state) == {CaptureTarget("1", monitor=False)}
    strip.close()
    plain.close()


# -- the buttons ----------------------------------------------------------------------------------------------------

LED = "vpn-status --watch"


async def test_an_led_shows_what_its_watch_prints(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'solo = {{ led = {{ watch = "{LED}" }} }}')
    strip.update(SPEAKER)
    s = surface.strips[0]
    assert s.leds[Button.SOLO] == Led.OFF
    for line, led in (("Yes", Led.ON), ("flash", Led.FLASH), ("no", Led.OFF), ("1", Led.ON)):
        programs.print_to(LED, line)
        await settle()
        assert s.leds[Button.SOLO] == led
    strip.close()


RESET = "brightness -d DP-1 --reset"


async def test_a_button_runs_a_program(surface: RecordingSurface, env: StripEnv, programs: ProgramCommands) -> None:
    strip = strip_of(surface, env, f'select = {{ press = {{ run = "{RESET}" }}, hold = {{ run = "say {{value}}" }} }}')
    strip.update(SPEAKER)
    strip.on_button(Button.SELECT, True)
    strip.on_button(Button.SELECT, False)
    await settle()
    assert ran(programs) == [RESET]
    # its LED stays off
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF
    # without a bound fader or encoder, `{value}` is the volume
    strip.on_button(Button.SELECT, True)
    await asyncio.sleep(1)
    strip.on_button(Button.SELECT, False)
    await settle()
    assert ran(programs)[-1] == "say 50"
    strip.close()


async def test_value_in_a_program_of_a_button_is_the_value_of_the_fader(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands, caplog: pytest.LogCaptureFixture
) -> None:
    strip = strip_of(surface, env, f'{FADER}\nsolo = {{ press = {{ run = "remember {{value}}" }} }}')
    strip.update(SPEAKER)
    with caplog.at_level(logging.WARNING):
        strip.on_button(Button.SOLO, True)
        await settle()
    # not known yet: nothing runs
    assert programs.runs == []
    assert "It.solo: remember needs the value, which is not known yet" in caplog.text
    programs.print_to(WATCH, "0.6")
    await settle()
    strip.on_button(Button.SOLO, True)
    await settle()
    assert ran(programs) == ["remember 0.6"]
    strip.close()


async def test_value_in_a_program_of_a_button_is_else_the_value_of_the_encoder(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'{ENCODER}\nrec = {{ press = {{ run = "remember {{value}}" }} }}')
    strip.update(SPEAKER)
    programs.print_to(WATCH, "0.25")
    await settle()
    strip.on_button(Button.REC, True)
    await settle()
    assert ran(programs) == ["remember 0.25"]
    assert strip.value_for_run() == 0.25
    strip.close()


async def test_a_program_of_a_button_that_fails_is_logged(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands, caplog: pytest.LogCaptureFixture
) -> None:
    programs.failing = "reset failed (1)"
    strip = strip_of(surface, env, f'select = {{ press = {{ run = "{RESET}" }} }}')
    strip.update(GONE)
    with caplog.at_level(logging.WARNING):
        strip.on_button(Button.SELECT, True)
        await settle()
    assert "It.select: reset failed (1)" in caplog.text
    strip.close()


async def test_value_for_a_program_is_the_volume_being_set(surface: RecordingSurface, env: StripEnv) -> None:
    strip = strip_of(surface, env, "")
    assert strip.value_for_run() is None
    strip.update(SPEAKER)
    strip.on_fader(0.7)
    assert strip.value_for_run() == 70
    await settle()
    strip.close()


# -- for as long as the controller lives ----------------------------------------------------------------------------


async def test_another_look_keeps_the_watches_that_stay(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'lcd = {{ watch = "{STATUS}" }}\ncolor = {{ watch = "{COLOR}" }}')
    strip.update(SPEAKER)
    await settle()
    assert len(programs.watches) == 2
    programs.print_to(COLOR, "red")
    await settle()
    (config,) = strips_of(
        f'[channel.it]\ntype = "output"\ndevice = "speaker"\nlcd = {{ watch = "{STATUS}" }}\n{ENCODER}'
    )
    strip.set_look(look_of(config))
    await settle()
    # the LCD's goes on, the color's ended, the encoder's started
    assert len(programs.watches) == 3
    assert set(strip.bound.lines) == {"lcd"}
    assert strip.bound.color is None
    assert isinstance(strip.knob, CommandKnob)
    strip.update(SPEAKER)
    assert surface.strips[0].color == Color.WHITE
    # back without the encoder: a knob of the type again
    (plain,) = strips_of('[channel.it]\ntype = "output"\ndevice = "speaker"')
    strip.set_look(look_of(plain))
    assert not isinstance(strip.knob, CommandKnob)
    assert strip.bound.lines == {}
    strip.close()


async def test_an_auto_strip_follows_the_bindings_of_its_place(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, "", kind='type = "auto"')
    assert isinstance(strip, AutoStrip)
    (config,) = strips_of(f'[channel.it]\ntype = "auto"\nlcd = {{ watch = "{STATUS}" }}')
    strip.set_look(look_of(config))
    strip.update(GONE)
    programs.print_to(STATUS, "Stopped")
    await settle()
    assert surface.strips[0].text[1] == "Stopped"
    strip.close()


async def test_closing_the_strip_ends_its_programs(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'{FADER}\nlcd = {{ watch = "{STATUS}" }}')
    await settle()
    strip.close()
    await programs.wait_closed()
    assert strip.bound.lines == {}
    assert strip.bound.fader is None


async def test_a_watch_that_ends_runs_again(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    strip = strip_of(surface, env, f'lcd = {{ watch = "{STATUS}" }}')
    strip.update(SPEAKER)
    programs.print_to(STATUS, "Playing")
    programs.print_to(STATUS, END)
    await settle()
    assert surface.strips[0].text[1] == "Playing"
    await asyncio.sleep(5)
    await settle()
    assert len(programs.watches) == 2
    strip.close()


async def test_simulated_the_value_starts_in_the_middle(
    surface: RecordingSurface, env: StripEnv, programs: ProgramCommands
) -> None:
    programs.simulated = True
    strip = strip_of(surface, env, FADER)
    strip.update(SPEAKER)
    assert surface.strips[0].fader == protocol.fader_value(0.5)
    strip.close()


async def test_on_the_device_the_meter_and_the_lcd_show_the_watches(
    surface: RecordingSurface, programs: ProgramCommands
) -> None:
    config = parse_config(
        f"""
[channel.it]
type = "output"
device = "speaker"
label = "It"
lcd = {{ watch = "{STATUS}" }}
meter = {{ watch = "{LOAD}" }}

[slots]
1 = "it"

[voip]
provider = "demo"
"""
    )
    rig = Rig(surface, config, commands=programs)
    rig.step(SPEAKER)
    programs.print_to(STATUS, "Playing")
    programs.print_to(LOAD, "100")
    await settle()
    assert surface.strips[0].text == ["It", "Playing"]
    rig.desk.show_meters()
    assert surface.meters(0)[-1] == protocol.METER_MAX
    rig.mixer.close()
    await programs.wait_closed()
