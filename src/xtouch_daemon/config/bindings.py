"""
Bindings (docs/development/design/bindings.md): what a part of a strip does instead of what its channel type says. A
part is bound to Home Assistant (`"homeassistant"`) or to programs of your own: a value they set and watch
(`ValueBinding`), a `watch` whose lines the part shows (`WatchBinding`, `LevelBinding`), a program a button runs
(`RunAction`). The targets of a `custom` channel (`Target`) fill `{target}` in its programs.

A part takes a word or a table; the unions of them are discriminated by `text_or_table()`, so a mistake in a table is
reported for the table only. Their tags (`TEXT`, `TABLE`, ...) start with `~`: `base.error_place()` leaves them out
of the places of errors.
"""

import re
import shlex
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Tag, ValidationInfo, field_validator

from xtouch_daemon.config.base import Meanings, Model
from xtouch_daemon.config.values import (
    COLORS,
    ENCODER_MODES,
    FADER_MODES,
    ColorName,
    Command,
    EncoderMode,
    FaderMode,
    Label,
)

VALUE = "{value}"
"""What `set` and `run` replace by the value."""
TARGET = "{target}"
"""What the programs of a `custom` channel with `targets` replace by the `value` of the target."""
PLACEHOLDERS = ("value", "target")
"""The names of the placeholders of programs; other text in braces stays as it is (e.g. `awk '{print}'`)."""
_PLACEHOLDER = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")

TEXT = "~text"
"""The tag of the words of a part (`"homeassistant"`, `"volume"`, `true`)."""
TABLE = "~table"
"""The tag of the tables of a part (a binding)."""
SWITCH = "~switch"
"""The tag of `true` and `false` of a part (the meter)."""
HOME_ASSISTANT = "homeassistant"
"""The word of a part that belongs to Home Assistant."""
FADER_PUSH = "fader.push: a fader has no push, only the encoder"


def text_or_table(value: object) -> str:
    """The tag of a value of a part: `TABLE` for a table (or a model), `TEXT` for anything else."""
    return TABLE if isinstance(value, Mapping | BaseModel) else TEXT


def switch_text_or_table(value: object) -> str:
    """The tag of a value of a part that can be switched: `SWITCH` for `true` and `false`, else `text_or_table()`."""
    return SWITCH if isinstance(value, bool) else text_or_table(value)


WORD_OR_TABLE = Discriminator(text_or_table)
"""Discriminates a union of `Annotated[..., Tag(TEXT)] | Annotated[..., Tag(TABLE)]`."""


def fill(argv: Sequence[str], **placeholders: str) -> list[str]:
    """The program with the placeholders replaced: `fill(argv, value="0.6")` turns `{value}` into `0.6`."""
    result: list[str] = []
    for part in argv:
        for name, text in placeholders.items():
            part = part.replace(f"{{{name}}}", text)
        result.append(part)
    return result


def placeholders_of(argv: Sequence[str]) -> set[str]:
    """The placeholders a program uses, by name (`value`, `target`)."""
    return {match.group(1) for part in argv for match in _PLACEHOLDER.finditer(part)}


def _no_value(argv: tuple[str, ...]) -> tuple[str, ...]:
    if "value" in placeholders_of(argv):
        raise ValueError(f"{VALUE} is for set and run: a watch has no value to give")
    return argv


class WatchBinding(Model):
    """A part that shows what a program of your own prints: a line per change."""

    watch: Command
    """
    A program that runs all the time and prints a line per change. The part shows the newest line. E.g.
    `["playerctl", "status", "--follow"]`.
    """

    @field_validator("watch")
    @classmethod
    def _watch_has_no_value(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _no_value(value)


class LevelBinding(WatchBinding):
    """A meter that shows a number a program of your own prints, between `min` and `max`."""

    watch: Command
    """
    A program that runs all the time and prints a number per change. The meter shows it. E.g. `["cpu-load",
    "--watch"]`.
    """
    min: float = 0
    """The number with the meter dark."""
    max: float = 100
    """The number with the meter full."""

    @field_validator("max")
    @classmethod
    def _above_min(cls, value: float, info: ValidationInfo) -> float:
        bottom = info.data.get("min")
        if bottom is not None and value <= bottom:
            raise ValueError(f"{value:g} is not above min ({bottom:g})")
        return value


class ValueBinding(Model):
    """A value that programs of your own set and watch, e.g. the brightness of a screen."""

    set: Command
    """
    The program that sets the value, then each argument. `{value}` in an argument is the new value. E.g.
    `["brightnessctl", "set", "{value}%"]`.
    """
    watch: Command | None = None
    """
    A program that runs all the time and prints the value, one line per change. The fader, the LED ring and the LCD
    follow it.
    """
    min: float = 0
    """The value with the fader at the bottom and the LED ring empty."""
    max: float = 100
    """The value with the fader at the top and the LED ring full."""
    step: float | None = None
    """How much one step of the encoder changes the value. By default `behavior.encoder_step` percent of the range."""
    push: float | None = None
    """The value a push of the encoder sets, e.g. the full brightness. Without it, a push does nothing."""
    format: str = "{value:g}"
    """How the LCD shows the value, in the format of Python. E.g. `{value:.0%}` shows 0.55 as `55%`."""

    @field_validator("set")
    @classmethod
    def _set_takes_the_value(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "value" not in placeholders_of(value[1:]):
            raise ValueError(f"no argument has {VALUE}, so the value goes nowhere")
        return value

    @field_validator("watch")
    @classmethod
    def _watch_has_no_value(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return value if value is None else _no_value(value)

    @field_validator("max")
    @classmethod
    def _above_min(cls, value: float, info: ValidationInfo) -> float:
        bottom = info.data.get("min")
        if bottom is not None and value <= bottom:
            raise ValueError(f"{value:g} is not above min ({bottom:g})")
        return value

    @field_validator("step")
    @classmethod
    def _a_step(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("needs to be above 0")
        return value

    @field_validator("push")
    @classmethod
    def _within_the_range(cls, value: float | None, info: ValidationInfo) -> float | None:
        bottom, top = info.data.get("min"), info.data.get("max")
        if value is not None and bottom is not None and top is not None and not bottom <= value <= top:
            raise ValueError(f"{value:g} is not between min ({bottom:g}) and max ({top:g})")
        return value

    @field_validator("format")
    @classmethod
    def _shows_a_value(cls, value: str) -> str:
        try:
            value.format(value=0.5)
        except (ValueError, KeyError, IndexError) as e:
            raise ValueError(f"{value} can't show a value: {e}") from e
        return value

    @property
    def programs(self) -> dict[str, tuple[str, ...]]:
        """Its programs, by option."""
        return {"set": self.set} | ({"watch": self.watch} if self.watch is not None else {})


class RunAction(Model):
    """A program of your own a button runs, to its end."""

    run: Command
    """
    The program a press runs, then each argument. `{value}` is the value of the fader, else of the encoder. E.g.
    `["sysctrl", "display", "reset"]`.
    """


class Target(Model):
    """One of the things a `custom` channel controls, e.g. one of two screens."""

    name: Label
    """The name on the LCD while the strip controls it, e.g. `Left`."""
    value: str
    """What `{target}` is in the programs of the channel, e.g. `DisplayPort-1`."""


def describe_part(part: object) -> str:
    """A part for people: its word, or what it is bound to (`a value from 0.1 to 1, set: ...`, `watch: ...`)."""
    match part:
        case ValueBinding():
            watch = f", watch: {shlex.join(part.watch)}" if part.watch is not None else ""
            return f"a value from {part.min:g} to {part.max:g}, set: {shlex.join(part.set)}{watch}"
        case LevelBinding():
            return f"from {part.min:g} to {part.max:g}, watch: {shlex.join(part.watch)}"
        case WatchBinding():
            return f"watch: {shlex.join(part.watch)}"
        case RunAction():
            return f"run {shlex.join(part.run)}"
        case _:
            return str(part)


def programs_in(config: BaseModel, parts: Sequence[str], buttons: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """The programs of the parts and buttons of a strip, by where they are, e.g. `fader.set`, `select.press.run`."""
    bound: dict[str, object] = {name: getattr(config, name) for name in parts}
    for name in buttons:
        table = getattr(config, name)
        bound |= {f"{name}.{key}": getattr(table, key) for key in ("press", "hold", "led")}
    return {f"{where}.{option}": argv for where, part in bound.items() for option, argv in programs_of(part).items()}


def programs_of(part: object) -> dict[str, tuple[str, ...]]:
    """The programs of a part, by option (`set`, `watch`, `run`): none for a word."""
    match part:
        case ValueBinding():
            return part.programs
        case WatchBinding():
            return {"watch": part.watch}
        case RunAction():
            return {"run": part.run}
        case _:
            return {}


# -- the parts of strips ---------------------------------------------------------------------------------------------

HomeAssistant = Literal["homeassistant"]

LCD_PARTS = Meanings(
    {"homeassistant": "Home Assistant sets the text: a text entity of its own. Needs `[mqtt]`."},
)
COLOR_PARTS = Meanings(
    {
        **COLORS.meanings,
        "homeassistant": "Home Assistant sets the color: a select entity of its own. Needs `[mqtt]`.",
    }
)
METER_PARTS = Meanings(
    {"homeassistant": "Home Assistant sets the level: a number entity of its own, from 0 to 100. Needs `[mqtt]`."}
)
VALUE_PARTS = Meanings(
    {"homeassistant": "Changes a number entity in Home Assistant (0..100). A push is an event there. Needs `[mqtt]`."}
)

ColorWord = Literal[ColorName, "homeassistant"]
"""A color by its name, or `homeassistant`."""

FaderPart = Annotated[
    Annotated[Annotated[FaderMode, FADER_MODES], Tag(TEXT)] | Annotated[ValueBinding, Tag(TABLE)],
    WORD_OR_TABLE,
]
"""What the fader of an audio strip sets: the volume, a number in Home Assistant, or a value of your own."""
EncoderPart = Annotated[
    Annotated[Annotated[EncoderMode, ENCODER_MODES], Tag(TEXT)] | Annotated[ValueBinding, Tag(TABLE)],
    WORD_OR_TABLE,
]
"""What the encoder of an audio strip does: a mode of the type, or a value of your own."""
LcdPart = Annotated[
    Annotated[Annotated[HomeAssistant, LCD_PARTS], Tag(TEXT)] | Annotated[WatchBinding, Tag(TABLE)],
    WORD_OR_TABLE,
]
"""What the second line of the LCD shows instead of what the type shows: Home Assistant's text, or a watch's."""
ColorPart = Annotated[
    Annotated[Annotated[ColorWord, COLOR_PARTS], Tag(TEXT)] | Annotated[WatchBinding, Tag(TABLE)],
    WORD_OR_TABLE,
]
"""The backlight of the LCD: a color, Home Assistant's, or the color a watch prints."""
MeterPart = Annotated[
    Annotated[bool, Tag(SWITCH)]
    | Annotated[Annotated[HomeAssistant, METER_PARTS], Tag(TEXT)]
    | Annotated[LevelBinding, Tag(TABLE)],
    Discriminator(switch_text_or_table),
]
"""What the meter of an audio strip shows: the level (`true`), nothing (`false`), Home Assistant's, or a watch's."""
CustomValuePart = Annotated[
    Annotated[Annotated[HomeAssistant, VALUE_PARTS], Tag(TEXT)] | Annotated[ValueBinding, Tag(TABLE)],
    WORD_OR_TABLE,
]
"""The fader or the encoder of a `custom` channel: a number in Home Assistant, or a value of your own."""
CustomMeterPart = Annotated[
    Annotated[Annotated[HomeAssistant, METER_PARTS], Tag(TEXT)] | Annotated[LevelBinding, Tag(TABLE)],
    WORD_OR_TABLE,
]
"""The meter of a `custom` channel: Home Assistant's level, or a watch's."""


def color_name(color: ColorName | ColorWord | WatchBinding) -> ColorName:
    """The color of a part as a name: a bound one is white until what it is bound to says otherwise."""
    return "white" if color == "homeassistant" or isinstance(color, WatchBinding) else color
