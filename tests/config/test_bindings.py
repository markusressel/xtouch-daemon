"""
Bindings: the parts of a strip bound to Home Assistant or to programs of your own, and custom channels, as the
configuration takes them, and the problems it finds, named by their place.
"""

import pytest
from pydantic import ValidationError

from xtouch_daemon.cli.configuration import describe_strip
from xtouch_daemon.config.base import ConfigError, error_place
from xtouch_daemon.config.bindings import (
    LevelBinding,
    RunAction,
    ValueBinding,
    WatchBinding,
    color_name,
    describe_part,
    fill,
    placeholders_of,
)
from xtouch_daemon.config.buttons import ButtonConfig, describe_action, indicator
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import CustomStripConfig

MQTT = '[mqtt]\nhost = "localhost"\n'


def channel(text: str, mqtt: bool = False) -> str:
    return (MQTT if mqtt else "") + '[slots]\n1 = "it"\n[channel.it]\n' + text


def strip_of(text: str, mqtt: bool = False) -> object:
    config = parse_config(channel(text, mqtt))
    assert config.slots is not None
    return config.slots.channels["it"]


def problems_of(text: str, mqtt: bool = False) -> str:
    with pytest.raises(ConfigError) as error:
        parse_config(channel(text, mqtt))
    return str(error.value)


def test_placeholders_are_filled_and_found():
    argv = ("b", "-d", "{target}", "{value}%", "awk '{print}'")
    assert fill(argv, value="0.6", target="DP-1") == ["b", "-d", "DP-1", "0.6%", "awk '{print}'"]
    assert fill(argv) == list(argv)
    assert placeholders_of(argv) == {"value", "target"}
    assert placeholders_of(("echo", "${value_of}", "{print}")) == set()


def test_the_places_of_errors_leave_out_the_kinds_of_values():
    assert error_place(("fader", "~table", "set")) == "fader.set"
    assert error_place(("select", "~run", "run", 0)) == "select.run.0"


def test_a_value_has_a_program_a_range_a_step_a_push_and_a_format():
    value = ValueBinding.model_validate({"set": "b -b {value}", "watch": ["b", "--watch"], "min": 0.1, "max": 1})
    assert (value.set, value.watch, value.min, value.max, value.step, value.push, value.format) == (
        ("b", "-b", "{value}"),
        ("b", "--watch"),
        0.1,
        1,
        None,
        None,
        "{value:g}",
    )
    assert value.programs == {"set": ("b", "-b", "{value}"), "watch": ("b", "--watch")}


@pytest.mark.parametrize(
    ("options", "problem"),
    [
        ({"set": ["brightness", "-b", "1"]}, "set: Value error, no argument has {value}"),
        ({"set": ["{value}"]}, "set: Value error, no argument has {value}"),
        ({"set": ""}, "set: Value error, an empty command"),
        ({"watch": "b {value}"}, "watch: Value error, {value} is for set and run"),
        ({"min": 1.0, "max": 0.1}, "max: Value error, 0.1 is not above min (1)"),
        ({"step": 0}, "step: Value error, needs to be above 0"),
        ({"push": 2.0}, "push: Value error, 2 is not between min (0) and max (1)"),
        ({"format": "{value:d}"}, "format: Value error, {value:d} can't show a value"),
        ({"format": "{level}"}, "format: Value error, {level} can't show a value"),
        ({"program": "x"}, "program: Extra inputs are not permitted"),
    ],
)
def test_a_value_needs_its_value_in_set_a_range_and_a_step(options: dict[str, object], problem: str) -> None:
    with pytest.raises(ValidationError) as error:
        ValueBinding.model_validate({"set": "b {value}", "max": 1} | options)
    assert problem in "\n".join(f"{error_place(e['loc'])}: {e['msg']}" for e in error.value.errors())


def test_a_watch_a_level_a_run_and_a_target():
    assert WatchBinding.model_validate({"watch": "status --follow"}).watch == ("status", "--follow")
    level = LevelBinding.model_validate({"watch": "load", "min": 10, "max": 20})
    assert (level.min, level.max) == (10, 20)
    with pytest.raises(ValidationError, match=r"max\n.*5 is not above min"):
        LevelBinding.model_validate({"watch": "load", "min": 10, "max": 5})
    with pytest.raises(ValidationError, match="for set and run"):
        WatchBinding.model_validate({"watch": "load {value}"})
    assert RunAction.model_validate({"run": "reset {value}"}).run == ("reset", "{value}")


def test_parts_are_described_for_people():
    value = ValueBinding.model_validate({"set": "b {value}", "watch": "b -w", "min": 0.1, "max": 1})
    assert describe_part(value) == "a value from 0.1 to 1, set: b '{value}', watch: b -w"
    assert describe_part(ValueBinding.model_validate({"set": "b {value}"})) == "a value from 0 to 100, set: b '{value}'"
    assert describe_part(LevelBinding.model_validate({"watch": "load"})) == "from 0 to 100, watch: load"
    assert describe_part(WatchBinding.model_validate({"watch": "status"})) == "watch: status"
    assert describe_part(RunAction.model_validate({"run": "reset now"})) == "run reset now"
    assert describe_action(RunAction.model_validate({"run": "reset"})) == "run reset"
    assert describe_part("homeassistant") == "homeassistant"
    assert color_name("cyan") == "cyan"
    assert color_name("homeassistant") == "white"
    assert color_name(WatchBinding.model_validate({"watch": "color"})) == "white"


def test_a_button_runs_a_program_and_its_led_watches_one():
    button = ButtonConfig.model_validate(
        {"press": {"run": "reset"}, "hold": {"launch": ["app"]}, "led": {"watch": "x"}}
    )
    assert button.press == RunAction(run=("reset",))
    assert isinstance(button.led, WatchBinding)
    assert indicator(button.led) is None
    assert indicator("homeassistant") is None
    assert indicator("muted") == "muted"
    assert ButtonConfig.model_validate({"led": "homeassistant"}).led == "homeassistant"


def test_an_audio_strip_binds_its_parts():
    strip = strip_of(
        'type = "output"\n'
        'fader = { set = "b {value}", watch = "b -w", min = 0.1, max = 1 }\n'
        'meter = { watch = "load", max = 8 }\n'
        'color = { watch = "color" }\n'
        'lcd = { watch = "status" }\n'
        'select = { press = { run = "reset" }, led = { watch = "lit" } }\n'
    )
    assert isinstance(strip, BaseStripConfig)
    assert isinstance(strip.fader, ValueBinding)
    assert isinstance(strip.meter, LevelBinding)
    assert isinstance(strip.color, WatchBinding)
    assert isinstance(strip.lcd, WatchBinding)
    assert not strip.uses_home_assistant
    assert set(strip.programs()) == {
        "fader.set",
        "fader.watch",
        "meter.watch",
        "color.watch",
        "lcd.watch",
        "select.press.run",
        "select.led.watch",
    }
    assert describe_strip(strip, "it") == (  # type: ignore[arg-type]
        "the default output (color: watch: color, meter: from 0 to 8, watch: load, lcd: watch: status, "
        "select: press run reset, LED watch: lit, rec: recording, solo: off, encoder: volume, "
        "fader: a value from 0.1 to 1, set: b '{value}', watch: b -w)"
    )
    # without bindings, as before
    plain = strip_of('type = "output"\nmeter = false\n')
    assert isinstance(plain, BaseStripConfig)
    assert (plain.fader, plain.encoder, plain.lcd, plain.color, plain.meter) == ("volume", None, None, "white", False)
    assert describe_strip(plain, "it").startswith("the default output (white, no meter, ")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        'type = "output"\ncolor = "homeassistant"\n',
        'type = "output"\nmeter = "homeassistant"\n',
        'type = "output"\nlcd = "homeassistant"\n',
        'type = "output"\nrec = "homeassistant"\n',
        'type = "output"\nsolo = { led = "homeassistant" }\n',
        'type = "custom"\nfader = "homeassistant"\n',
        'type = "custom"\nmute = { press = "homeassistant" }\n',
        'type = "custom"\nselect = { led = "homeassistant" }\n',
    ],
)
def test_every_part_in_home_assistant_needs_mqtt(text: str) -> None:
    assert "channel.it: Home Assistant needs an [mqtt] section" in problems_of(text)
    strip = strip_of(text, mqtt=True)
    assert getattr(strip, "uses_home_assistant", False)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('fader = { set = "b {value}", push = 1 }\n', "channel.it: fader.push: a fader has no push, only the encoder"),
        ('fader = { set = "b" }\n', "channel.it: fader.set: no argument has {value}"),
        ('fader = { set = "b {value}" }\nencoder = "balance"\n', "with the fader bound to a program, the encoder sets"),
        ('fader = "homeassistant"\nencoder = "balance"\n', "with the fader in Home Assistant, the encoder sets"),
        ('fader = "loud"\n', "channel.it: fader: Input should be 'volume' or 'homeassistant'"),
        ('encoder = "pick"\n', "channel.it: encoder: pick is not for output strips"),
        ('encoder = { set = "b {value}", step = -1 }\n', "channel.it: encoder.step: needs to be above 0"),
        ('meter = "loud"\n', "channel.it: meter: Input should be 'homeassistant'"),
        ('meter = { watch = "load", min = 5, max = 5 }\n', "channel.it: meter.max: 5 is not above min (5)"),
        ('color = "pink"\n', "channel.it: color: Input should be 'off', 'red',"),
        ('lcd = { text = "x" }\n', "channel.it: lcd.watch: Field required"),
        ('lcd = { watch = "s {target}" }\n', "channel.it: lcd.watch: {target} is for custom channels with targets"),
        ('select = { press = { run = "" } }\n', "channel.it: select.press.run: an empty command"),
        ('rec = { led = "blink" }\n', "channel.it: rec.led: Input should be 'off', 'recording',"),
        ('solo = { led = { watch = "x {value}" } }\n', "channel.it: solo.led.watch: {value} is for set and run"),
    ],
)
def test_the_problems_of_bindings_name_their_place(text: str, problem: str) -> None:
    assert problem in problems_of('type = "output"\n' + text)


def test_a_custom_channel_binds_every_part():
    strip = strip_of(
        'type = "custom"\n'
        'label = "Screens"\n'
        'targets = [{ name = "Left", value = "DP-1" }, { name = "Right", value = "DP-2" }]\n'
        'fader = { set = "b -d {target} -b {value}", watch = "b -d {target} -w", min = 0.1, max = 1 }\n'
        'encoder = { set = "c {value}", push = 50 }\n'
        'meter = { watch = "load" }\n'
        'present = { watch = "screens --watch" }\n'
        'select = { press = "next", led = "press" }\n'
        'mute = { press = { run = "reset {value}" }, hold = "toggle:night", led = { watch = "muted" } }\n'
        "[state.night]\nprocesses = ['redshift']\n"
    )
    assert isinstance(strip, CustomStripConfig)
    assert [target.name for target in strip.targets] == ["Left", "Right"]
    assert strip.button("select").press == "next"
    assert strip.button("rec").press == "off"
    assert not strip.uses_home_assistant
    assert strip.value_bound
    assert describe_strip(strip, "it") == (
        "'Screens' custom for Left, Right (white, fader: a value from 0.1 to 1, set: b -d '{target}' -b '{value}', "
        "watch: b -d '{target}' -w, encoder: a value from 0 to 100, set: c '{value}', meter: from 0 to 100, "
        "watch: load, present: watch: screens --watch, select: press next, LED press, mute: press run reset "
        "'{value}', hold toggle:night, LED watch: muted)"
    )
    together = strip_of(
        'type = "custom"\ntargets = [{ name = "A", value = "1" }]\ntogether = true\n'
        'fader = { set = "b {target} {value}" }\n'
    )
    assert describe_strip(together, "it").startswith("custom for A together (white, ")  # type: ignore[arg-type]
    assert describe_strip(strip_of('type = "custom"\n'), "it") == "custom (white)"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('fader = { set = "b {value}", push = 1 }\n', "channel.it: fader.push: a fader has no push, only the encoder"),
        ('fader = "volume"\n', "channel.it: fader: Input should be 'homeassistant'"),
        ('encoder = "balance"\n', "channel.it: encoder: Input should be 'homeassistant'"),
        ("meter = true\n", "channel.it: meter: Input should be 'homeassistant'"),
        ('fader = { set = "b {target} {value}" }\n', "channel.it: fader.set: {target} needs targets"),
        ("together = true\n", "channel.it: together: needs targets"),
        (
            'targets = [{ name = "A", value = "1" }, { name = "A", value = "2" }]\n',
            "channel.it: targets: two targets named A: the LCD tells them apart by their names",
        ),
        (
            'targets = [{ name = "A", value = "1" }]\nfader = { set = "b {value}" }\n',
            "channel.it: targets: no program has {target}, so the targets would all be the same",
        ),
        (
            'targets = [{ name = "Too long a name", value = "1" }]\n',
            "channel.it: targets.0.name: String should have at",
        ),
        ('select = { press = "next" }\n', "channel.it: select.press: next needs at least two targets"),
        (
            'targets = [{ name = "A", value = "1" }, { name = "B", value = "2" }]\ntogether = true\n'
            'fader = { set = "b {target} {value}" }\nselect = { press = "next" }\n',
            "channel.it: select.press: next switches nothing with together",
        ),
        ('rec = { press = "default" }\n', "channel.it: rec.press: default is not for custom channels (cycle_modes,"),
        ('solo = { hold = "talk" }\n', "channel.it: solo.hold: talk is not for custom channels"),
        ('mute = { press = { launch = ["app"] } }\n', "channel.it: mute.press: a custom channel runs programs"),
        ('select = { hold = "homeassistant" }\n', 'channel.it: select.hold: "homeassistant" takes the whole button'),
        (
            'select = { press = "homeassistant", hold = "cycle_modes" }\n',
            "channel.it: select.hold: homeassistant lasts while the button is held",
        ),
        ('rec = "recording"\n', "channel.it: rec.led: recording is not for custom channels (homeassistant, off,"),
        # an unknown word gets the words of the custom type, not those of the audio strips
        ('select = { press = "mute" }\n', "channel.it: select.press: mute is not for custom channels (cycle_modes,"),
        ('select = { led = "mute" }\n', "channel.it: select.led: mute is not for custom channels (homeassistant, off,"),
        ('mute = "blink"\n', "channel.it: mute.led: blink is not for custom channels"),
        ('select = { press = { run = "x {value}" } }\n', "channel.it: select.press.run: {value} needs a fader or an"),
        ('mute = { press = "mode:nope" }\n', "channel.it.mute.press: mode:nope: no mode nope"),
        ('present = { watch = "" }\n', "channel.it: present.watch: an empty command"),
    ],
)
def test_the_problems_of_custom_channels_name_their_place(text: str, problem: str) -> None:
    assert problem in problems_of('type = "custom"\n' + text, mqtt=True)


def test_command_channels_are_custom_channels_now():
    assert "channel.it.type: Input should be" in problems_of('type = "command"\nset = "b {value}"\n')
