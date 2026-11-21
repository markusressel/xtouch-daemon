"""
Bindings (docs/development/design/bindings.md): what a part of a strip does instead of what its channel type says. A
part is bound to Home Assistant (`"homeassistant"`), to programs of your own: a value they set and watch
(`ValueBinding`), a `watch` whose lines the part shows (`WatchBinding`, `LevelBinding`), a program a button runs
(`RunAction`); or to an entity of Home Assistant itself, through its API (`[homeassistant]`): its state the part shows
(`EntityBinding`, `EntityLevelBinding`), a value of it the fader or the encoder sets (`EntityValueBinding`), a service
a button calls (`ServiceAction`). The targets of a `custom` channel (`Target`) fill `{target}` in its programs.

A part takes a word or a table; the unions of them are discriminated by `text_or_table()`, so a mistake in a table is
reported for the table only. Their tags (`TEXT`, `TABLE`, ...) start with `~`: `base.error_place()` leaves them out
of the places of errors.
"""

import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    Discriminator,
    Field,
    JsonValue,
    Tag,
    ValidationInfo,
    field_validator,
    model_validator,
)

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
from xtouch_daemon.homeassistant.domains import ENTITY_ID, SERVICE, domain_of, domain_value

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
ENTITY = "~entity"
"""The tag of the tables of a part with an entity of Home Assistant (`{ entity = "..." }`)."""
SWITCH = "~switch"
"""The tag of `true` and `false` of a part (the meter)."""
HOME_ASSISTANT = "homeassistant"
"""The word of a part that belongs to Home Assistant."""
FADER_PUSH = "fader.push: a fader has no push, only the encoder"


def text_or_table(value: object) -> str:
    """
    The tag of a value of a part: `ENTITY` for a table with an `entity` (or an entity binding), `TABLE` for another
    table (or a model), `TEXT` for anything else.
    """
    if isinstance(value, EntityBinding) or (isinstance(value, Mapping) and "entity" in value):
        return ENTITY
    return TABLE if isinstance(value, Mapping | BaseModel) else TEXT


def switch_text_or_table(value: object) -> str:
    """The tag of a value of a part that can be switched: `SWITCH` for `true` and `false`, else `text_or_table()`."""
    return SWITCH if isinstance(value, bool) else text_or_table(value)


WORD_OR_TABLE = Discriminator(text_or_table)
"""
Discriminates a union of `Annotated[..., Tag(TEXT)] | Annotated[..., Tag(TABLE)] | Annotated[..., Tag(ENTITY)]`.
"""


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


def _no_value(argv: tuple[str, ...] | None, info: ValidationInfo) -> tuple[str, ...] | None:
    if argv is not None and "value" in placeholders_of(argv):
        raise ValueError(f"{VALUE} is for set and run: a {info.field_name} has no value to give")
    return argv


POLL_EVERY = 10.0
"""Seconds between the runs of a `poll` program without `every`."""


@dataclass(frozen=True)
class Feed:
    """
    A program whose lines a part takes: one that runs all the time and prints a line per change (`watch`), or one
    that runs to its end every `every` seconds and gives the last line it printed (`poll`).
    """

    argv: tuple[str, ...]
    every: float | None = None
    """Seconds from one run of a `poll` to the next; None for a `watch`."""

    @property
    def option(self) -> str:
        """The option it comes from: `watch` or `poll`."""
        return "watch" if self.every is None else "poll"

    def filled(self, **placeholders: str) -> Feed:
        """The same with the placeholders of its program filled in (`{target}`)."""
        return replace(self, argv=tuple(fill(self.argv, **placeholders)))

    def __str__(self) -> str:
        every = f" (every {self.every:g} s)" if self.every is not None else ""
        return f"{self.option}: {shlex.join(self.argv)}{every}"


def _feed_of(binding: WatchBinding | ValueBinding) -> Feed | None:
    """The feed of a binding with `watch` or `poll`; None for one with neither (a `ValueBinding` without a watch)."""
    if binding.poll is not None:
        return Feed(binding.poll, binding.every)
    return Feed(binding.watch) if binding.watch is not None else None


def _one_feed(binding: WatchBinding | ValueBinding, needed: bool) -> None:
    """`watch` and `poll` are one or the other, `every` is for `poll`; `needed`: one of them is a must."""
    if binding.watch is not None and binding.poll is not None:
        raise ValueError(
            "watch and poll: give one of them, watch for a program that runs all the time, poll for one that ends"
        )
    if needed and binding.watch is None and binding.poll is None:
        raise ValueError("watch or poll: give the program that prints the lines")
    if "every" in binding.model_fields_set and binding.poll is None:
        raise ValueError("every: is for poll, which has none here")


class WatchBinding(Model):
    """A part that shows what a program of your own prints: a line per change, or the last line of each run."""

    watch: Command | None = None
    """
    A program that runs all the time and prints a line per change. The part shows the newest line. E.g.
    `["playerctl", "status", "--follow"]`.
    """
    poll: Command | None = None
    """
    A program that runs to its end every `every` seconds. The part shows the last line it prints. E.g.
    `"date +%H:%M"`.
    """
    every: float = Field(POLL_EVERY, gt=0)
    """Seconds from one run of `poll` to the next. A run that takes longer is stopped."""

    @field_validator("watch", "poll")
    @classmethod
    def _programs_have_no_value(cls, value: tuple[str, ...] | None, info: ValidationInfo) -> tuple[str, ...] | None:
        return _no_value(value, info)

    @model_validator(mode="after")
    def _a_feed(self) -> Self:
        _one_feed(self, needed=True)
        return self

    @property
    def feed(self) -> Feed:
        """The program it takes the lines of."""
        feed = _feed_of(self)
        assert feed is not None, "watch or poll (checked when the file is loaded)"
        return feed

    def filled(self, **placeholders: str) -> Self:
        """The same with the placeholders of its programs filled in (`{target}`)."""
        return self.model_copy(
            update={
                option: tuple(fill(argv, **placeholders))
                for option in ("watch", "poll")
                if (argv := getattr(self, option)) is not None
            }
        )


class LevelBinding(WatchBinding):
    """A meter that shows a number that a program of your own prints, between `min` and `max`."""

    watch: Command | None = None
    """
    A program that runs all the time and prints a number per change. The meter shows it. E.g. a script of your own
    that prints the CPU load: `"/home/me/bin/cpu-load"`.
    """
    poll: Command | None = None
    """
    A program that runs to its end every `every` seconds and prints a number. The meter shows the last one. E.g.
    `["cat", "/sys/class/power_supply/BAT0/capacity"]`.
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
    poll: Command | None = None
    """
    A program that runs to its end every `every` seconds and prints the value. The fader, the LED ring and the LCD
    follow it.
    """
    every: float = Field(POLL_EVERY, gt=0)
    """Seconds from one run of `poll` to the next. A run that takes longer is stopped."""
    min: float = 0
    """The value with the fader at the bottom and the LED ring empty."""
    max: float = 100
    """The value with the fader at the top and the LED ring full."""
    step: float | None = None
    """How much one step of the encoder changes the value. By default `behavior.encoder_step` percent of the range."""
    push: float | None = None
    """The value a push of the encoder sets. Without it, a push does nothing. E.g. the full brightness."""
    format: str = "{value:g}"
    """How the LCD shows the value, in the format of Python. E.g. `{value:.0%}` shows 0.55 as `55%`."""

    @field_validator("set")
    @classmethod
    def _set_takes_the_value(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "value" not in placeholders_of(value[1:]):
            raise ValueError(f"no argument has {VALUE}, so the value goes nowhere")
        return value

    @field_validator("watch", "poll")
    @classmethod
    def _programs_have_no_value(cls, value: tuple[str, ...] | None, info: ValidationInfo) -> tuple[str, ...] | None:
        return _no_value(value, info)

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

    @model_validator(mode="after")
    def _a_feed(self) -> Self:
        _one_feed(self, needed=False)
        return self

    @property
    def feed(self) -> Feed | None:
        """The program it follows the value of; None without `watch` and `poll`."""
        return _feed_of(self)

    @property
    def programs(self) -> dict[str, tuple[str, ...]]:
        """Its programs, by option."""
        feed = self.feed
        return {"set": self.set} | ({feed.option: feed.argv} if feed is not None else {})


class RunAction(Model):
    """A program of your own that a button runs to its end."""

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


def _entity_id(value: str) -> str:
    if not ENTITY_ID.fullmatch(value):
        raise ValueError(f"{value} is no entity ID (<domain>.<name>, e.g. sensor.cpu_temp)")
    return value


def _service(value: str) -> str:
    if not SERVICE.fullmatch(value):
        raise ValueError(f"{value} is no service (<domain>.<service>, e.g. light.toggle)")
    return value


EntityId = Annotated[str, AfterValidator(_entity_id)]
"""The id of an entity of Home Assistant, e.g. `sensor.cpu_temp`."""
ServiceName = Annotated[str, AfterValidator(_service)]
"""A service of Home Assistant, e.g. `light.toggle`."""
ServiceData = dict[str, JsonValue]
"""The data of a service call, as Home Assistant takes it."""


def _has_value(data: object) -> bool:
    """Whether `{value}` is in the data of a service, at any depth."""
    if isinstance(data, str):
        return VALUE in data
    if isinstance(data, Mapping):
        return any(_has_value(item) for item in data.values())  # pyright: ignore[reportUnknownVariableType]
    if isinstance(data, list):
        return any(_has_value(item) for item in data)  # pyright: ignore[reportUnknownVariableType]
    return False


def fill_data(data: JsonValue, value: float) -> JsonValue:
    """
    The data of a service with the value in it: a text that is `{value}` becomes the number, `{value}` in another
    text its digits (`value_text()` of `strips.value`).
    """
    number: JsonValue = int(value) if float(value).is_integer() else value
    if data == VALUE:
        return number
    if isinstance(data, str):
        return data.replace(VALUE, str(number))
    if isinstance(data, dict):
        return {key: fill_data(item, value) for key, item in data.items()}
    if isinstance(data, list):
        return [fill_data(item, value) for item in data]
    return data


class _Hashed(Model):
    # frozen models hash their fields; the data of a service is a dict
    def __hash__(self) -> int:
        return hash((type(self), self.model_dump_json()))


class EntityBinding(_Hashed):
    """A part that shows an entity of Home Assistant: its state, or one of its attributes."""

    entity: EntityId
    """The entity, by its ID. E.g. `sensor.cpu_temp`."""
    attribute: str | None = None
    """An attribute of the entity to show instead of its state. E.g. `temperature` of a `climate` entity."""


class EntityLevelBinding(EntityBinding):
    """A meter that shows a number of an entity of Home Assistant, between `min` and `max`."""

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


class EntityValueBinding(EntityBinding):
    """A value of an entity of Home Assistant that the fader or the encoder sets, e.g. the brightness of a light."""

    attribute: str | None = None
    """
    The attribute with the value, instead of the state. By default the one of the domain, e.g. `brightness` of a
    `light`.
    """
    min: float | None = None
    """The value with the fader at the bottom. By default the entity's `min`, else that of its domain, else 0."""
    max: float | None = None
    """The value with the fader at the top. By default the entity's `max`, else that of its domain, else 100."""
    step: float | None = None
    """How much one step of the encoder changes the value. By default `behavior.encoder_step` percent of the range."""
    push: float | None = None
    """The value a push of the encoder sets. Without it, a push does nothing."""
    format: str = "{value:g}"
    """How the LCD shows the value, in the format of Python. E.g. `{value:.0%}` shows 0.55 as `55%`."""
    service: ServiceName | None = None
    """
    The service a move calls, with the entity as its target. By default the one of the domain, e.g. `light.turn_on`.
    E.g. `script.set_level`.
    """
    data: ServiceData | None = None
    """The data of `service`. `{value}` in it is the new value. E.g. `{ level = "{value}" }`."""

    @model_validator(mode="after")
    def _settable(self) -> EntityValueBinding:
        if self.min is not None and self.max is not None and self.max <= self.min:
            raise ValueError(f"max: {self.max:g} is not above min ({self.min:g})")
        if self.step is not None and self.step <= 0:
            raise ValueError("step: needs to be above 0")
        if self.push is not None and not (
            (self.min is None or self.min <= self.push) and (self.max is None or self.push <= self.max)
        ):
            raise ValueError(f"push: {self.push:g} is not between min and max")
        try:
            self.format.format(value=0.5)
        except (ValueError, KeyError, IndexError) as e:
            raise ValueError(f"format: {self.format} can't show a value: {e}") from e
        if self.service is None:
            if self.data is not None:
                raise ValueError("data: is for service, which has none here")
            if domain_value(self.entity, self.attribute) is None:
                what = f"the attribute {self.attribute}" if self.attribute is not None else "the state"
                raise ValueError(
                    f"service: nothing sets {what} of a {domain_of(self.entity)} entity by itself: set service "
                    f"and data with {VALUE}"
                )
        elif not _has_value(self.data):
            raise ValueError(f"data: nothing has {VALUE}, so the value goes nowhere")
        return self


class ServiceAction(_Hashed):
    """A service of Home Assistant that a press calls, e.g. `light.toggle` of a light."""

    service: ServiceName
    """The service. E.g. `light.toggle`."""
    entity: EntityId | None = None
    """The entity the service acts on. E.g. `light.desk`."""
    data: ServiceData | None = None
    """
    More data for the service, sent as it is: `{value}` is for a fader or an encoder. E.g. `{ brightness_pct = 50 }`.
    """

    @model_validator(mode="after")
    def _as_it_is(self) -> ServiceAction:
        # a press sends its data as it is: `{value}` would arrive as the text
        if _has_value(self.data):
            raise ValueError(f"data: {VALUE} is for a fader or an encoder; a press sends the data as it is")
        return self


def describe_part(part: object) -> str:
    """A part for people: its word, or what it is bound to (`a value from 0.1 to 1, set: ...`, `watch: ...`)."""
    match part:
        case ValueBinding():
            feed = f", {part.feed}" if part.feed is not None else ""
            return f"a value from {part.min:g} to {part.max:g}, set: {shlex.join(part.set)}{feed}"
        case LevelBinding():
            return f"from {part.min:g} to {part.max:g}, {part.feed}"
        case WatchBinding():
            return str(part.feed)
        case RunAction():
            return f"run {shlex.join(part.run)}"
        case EntityValueBinding():
            return f"a value of {_entity_place(part)}"
        case EntityLevelBinding():
            return f"from {part.min:g} to {part.max:g}, {_entity_place(part)}"
        case EntityBinding():
            return _entity_place(part)
        case ServiceAction():
            return f"call {part.service}" + (f" on {part.entity}" if part.entity is not None else "")
        case _:
            return str(part)


def _entity_place(part: EntityBinding) -> str:
    return f"{part.entity}" + (f" ({part.attribute})" if part.attribute is not None else "")


def programs_in(config: BaseModel, parts: Sequence[str], buttons: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """The programs of the parts and buttons of a strip, by where they are, e.g. `fader.set`, `select.press.run`."""
    bound: dict[str, object] = {name: getattr(config, name) for name in parts}
    for name in buttons:
        table = getattr(config, name)
        bound |= {f"{name}.{key}": getattr(table, key) for key in ("press", "hold", "led")}
    return {f"{where}.{option}": argv for where, part in bound.items() for option, argv in programs_of(part).items()}


def programs_of(part: object) -> dict[str, tuple[str, ...]]:
    """The programs of a part, by option (`set`, `watch`, `poll`, `run`): none for a word."""
    match part:
        case ValueBinding():
            return part.programs
        case WatchBinding():
            return {part.feed.option: part.feed.argv}
        case RunAction():
            return {"run": part.run}
        case _:
            return {}


def entities_in(
    config: BaseModel, parts: Sequence[str], buttons: Sequence[str]
) -> dict[str, EntityBinding | ServiceAction]:
    """
    The parts and actions of a strip with entities of Home Assistant, by where they are, e.g. `meter`, `select.press`,
    `select.led`.
    """
    bound: dict[str, object] = {name: getattr(config, name) for name in parts}
    for name in buttons:
        table = getattr(config, name)
        bound |= {f"{name}.{key}": getattr(table, key) for key in ("press", "hold", "led")}
    return entities_of(bound)


def entities_of(parts: Mapping[str, object]) -> dict[str, EntityBinding | ServiceAction]:
    """Of parts by where they are, those with entities of Home Assistant (`EntityBinding`, `ServiceAction`)."""
    return {where: part for where, part in parts.items() if isinstance(part, EntityBinding | ServiceAction)}


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
    Annotated[Annotated[FaderMode, FADER_MODES], Tag(TEXT)]
    | Annotated[ValueBinding, Tag(TABLE)]
    | Annotated[EntityValueBinding, Tag(ENTITY)],
    WORD_OR_TABLE,
]
"""
What the fader of an audio strip sets: the volume, a number in Home Assistant, a value of your own, or of an entity.
"""
EncoderPart = Annotated[
    Annotated[Annotated[EncoderMode, ENCODER_MODES], Tag(TEXT)]
    | Annotated[ValueBinding, Tag(TABLE)]
    | Annotated[EntityValueBinding, Tag(ENTITY)],
    WORD_OR_TABLE,
]
"""What the encoder of an audio strip does: a mode of the type, a value of your own, or of an entity."""
LcdPart = Annotated[
    Annotated[Annotated[HomeAssistant, LCD_PARTS], Tag(TEXT)]
    | Annotated[WatchBinding, Tag(TABLE)]
    | Annotated[EntityBinding, Tag(ENTITY)],
    WORD_OR_TABLE,
]
"""
What the second line of the LCD shows instead of what the type shows: Home Assistant's text, a watch's, or an entity.
"""
ColorPart = Annotated[
    Annotated[Annotated[ColorWord, COLOR_PARTS], Tag(TEXT)]
    | Annotated[WatchBinding, Tag(TABLE)]
    | Annotated[EntityBinding, Tag(ENTITY)],
    WORD_OR_TABLE,
]
"""The backlight of the LCD: a color, Home Assistant's, the color a watch prints, or the color of an entity."""
MeterPart = Annotated[
    Annotated[bool, Tag(SWITCH)]
    | Annotated[Annotated[HomeAssistant, METER_PARTS], Tag(TEXT)]
    | Annotated[LevelBinding, Tag(TABLE)]
    | Annotated[EntityLevelBinding, Tag(ENTITY)],
    Discriminator(switch_text_or_table),
]
"""
What the meter of an audio strip shows: the level (`true`), nothing (`false`), Home Assistant's, a watch's, or an
entity's.
"""
CustomValuePart = Annotated[
    Annotated[Annotated[HomeAssistant, VALUE_PARTS], Tag(TEXT)]
    | Annotated[ValueBinding, Tag(TABLE)]
    | Annotated[EntityValueBinding, Tag(ENTITY)],
    WORD_OR_TABLE,
]
"""The fader or the encoder of a `custom` channel: a number in Home Assistant, a value of your own, or of an entity."""
CustomMeterPart = Annotated[
    Annotated[Annotated[HomeAssistant, METER_PARTS], Tag(TEXT)]
    | Annotated[LevelBinding, Tag(TABLE)]
    | Annotated[EntityLevelBinding, Tag(ENTITY)],
    WORD_OR_TABLE,
]
"""The meter of a `custom` channel: Home Assistant's level, a watch's, or an entity's."""
PresentPart = Annotated[
    Annotated[WatchBinding, Tag(TABLE)] | Annotated[EntityBinding, Tag(ENTITY)],
    Discriminator(lambda value: ENTITY if text_or_table(value) == ENTITY else TABLE),
]
"""Whether a `custom` channel is there: by the lines of a watch, or by an entity."""
LineBinding = WatchBinding | EntityBinding
"""A part that shows lines: of a watch, or the state of an entity (see `strips.value.open_line()`)."""


def color_name(color: ColorName | ColorWord | WatchBinding | EntityBinding) -> ColorName:
    """The color of a part as a name: a bound one is white until what it is bound to says otherwise."""
    return "white" if color == "homeassistant" or isinstance(color, WatchBinding | EntityBinding) else color
