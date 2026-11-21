"""
What a place (a candidate of a slot in table form) takes for the options it leaves unset: the options of the channel it
shows, or of its pool, else the defaults of the strip type; and the help of its form, which says so.
"""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from xtouch_daemon.config.bindings import HOME_ASSISTANT
from xtouch_daemon.config.buttons import default_setup, describe_action, table_of
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import default_encoder
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES
from xtouch_daemon.gui.domain.schema import describe, strip_options
from xtouch_daemon.gui.domain.slot_stacks import EMPTY, is_pool, pool_kind, pool_strip
from xtouch_daemon.slots.model import DEVICES, MEMBER_OPTIONS

PROGRAM_KEYS = ("launch", "run", "watch")
"""The tables of a part, by their key: what a press starts or runs, what an LED or a meter watches."""


HOME_ASSISTANT_KEYS = ("service", "entity")
"""The tables of a part with Home Assistant, by their key: the service a press calls, the entity a part shows."""


def program_text(table: Mapping[str, Any]) -> str:
    """
    A table of a part as a list shows it: `launch: mumble -m`, `run: ...`, `watch: ...`; with Home Assistant
    `service: light.toggle` or `entity: light.desk` (its other options show below the list).
    """
    for key in HOME_ASSISTANT_KEYS:
        if key in table:
            return f"{key}: {table[key]}"
    key = next((key for key in PROGRAM_KEYS if key in table), "launch")
    command = table.get(key, ())
    return f"{key}: " + (command if isinstance(command, str) else shlex.join(map(str, command)))


class Source(StrEnum):
    """Where a place takes what it leaves unset."""

    CHANNEL = "channel"
    """The channel it shows."""
    POOL = "pool"
    """Its pool (`[pool.apps]`, ...), else the strip type of what the pool hands out."""
    CHANNELS = "channels"
    """Each channel a pool of channels hands out: they bring their own."""


@dataclass(frozen=True)
class Origin:
    """What a place of `show` takes for the options it leaves unset."""

    show: str
    source: Source
    strip: str
    """The strip type: its defaults are for what the channel or the pool leaves unset too."""
    options: Mapping[str, Any] = field(default_factory=dict[str, Any])
    """The options of the channel or the pool in the file."""
    behavior: Mapping[str, Any] = field(default_factory=dict[str, Any])
    """`[behavior]` of the file: the defaults of the meter and the volume."""

    @property
    def prefix(self) -> str:
        """The start of a placeholder: "As on the channel: red"."""
        match self.source:
            case Source.CHANNEL:
                return "As on the channel"
            case Source.POOL:
                return "As in the pool"
            case Source.CHANNELS:
                return "As on each channel"

    @property
    def unset(self) -> str:
        """The end of the help of an option of the place: what unset means."""
        match self.source:
            case Source.CHANNEL:
                return "Unset: as on the channel."
            case Source.POOL:
                return f"Unset: as in `[pool.{self.show}]`."
            case Source.CHANNELS:
                return f"Unset: as on each channel of `{self.show}`."

    @property
    def back(self) -> str:
        """The tip of the button that unsets an option of the place."""
        match self.source:
            case Source.CHANNEL:
                return "Unset: as on the channel"
            case Source.POOL:
                return f"Unset: as in pool {self.show}"
            case Source.CHANNELS:
                return "Unset: as on each channel"

    @property
    def parts(self) -> str:
        """The line at the top of the form: where the parts of what the place shows are set."""
        match self.source:
            case Source.CHANNEL:
                return f"What the parts of `{self.show}` do is set on the channel."
            case Source.POOL:
                return f"What the parts of `{self.show}` do is set in the pool."
            case Source.CHANNELS:
                return (
                    f"Each channel of `{self.show}` brings its own look and what its parts do: set them on the "
                    "channels."
                )


def origin(values: Mapping[str, Any], show: str) -> Origin | None:
    """What a place of `show` takes for what it leaves unset (`values`: the file); None for `-` and unknown names."""
    behavior: Mapping[str, Any] = values.get("behavior", {})
    channel = values.get("channel", {}).get(show)
    if isinstance(channel, Mapping):
        kind = CHANNEL_TYPES.get(str(channel.get("type")))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        if kind is None:
            return None
        return Origin(show, Source.CHANNEL, kind.strip, dict(channel), behavior)  # pyright: ignore[reportUnknownArgumentType]
    if show == EMPTY or not is_pool(values, show):
        return None
    strip = pool_strip(show, values)
    assert strip is not None
    if pool_kind(values, show) == "channels":
        return Origin(show, Source.CHANNELS, strip, {}, behavior)
    pool: Mapping[str, Any] = values.get("pool", {}).get(show, {})
    look = {key: value for key, value in pool.items() if key not in MEMBER_OPTIONS}
    return Origin(show, Source.POOL, strip, look, behavior)


def value_text(value: object) -> str:
    """A value of the file for people: `on`, a word, `watch: cpu-load`."""
    if isinstance(value, Mapping):
        return program_text(value)  # pyright: ignore[reportUnknownArgumentType]
    return describe(value)


def inherited(place: Origin, name: str, pick: bool = True) -> str | None:
    """
    The value an option the place leaves unset takes, as a word (as the field shows it); None where it is not known
    (a label the strip makes of what it shows, the channels of a pool of channels). `pick`: the encoder may pick.
    """
    if place.source is Source.CHANNELS:
        return None
    options = place.options
    if name == "meter":
        meter = options.get("meter")
        if meter is False:
            return "off"
        if meter == HOME_ASSISTANT or isinstance(meter, Mapping):
            return value_text(meter)
        return str(options.get("meter_point") or place.behavior.get("meter_point") or BehaviorConfig().meter_point)
    value = options.get(name)
    if value is not None:
        return f"{value} %" if name in ("min_volume", "max_volume") else value_text(value)
    match name:
        case "encoder":
            return default_encoder("apps" if not pick else place.strip)
        case "min_volume":
            return "0 %"
        case "max_volume":
            return f"{place.behavior.get('max_volume') or BehaviorConfig().max_volume} %"
        case _:
            default = next((option.default for option in strip_options(place.strip) if option.name == name), None)
            return None if default is None else describe(default)


def inherited_part(place: Origin, button: str, part: str) -> str | None:
    """
    What a part (`press`, `led`) of a button the place leaves unset does, as the list shows it: the table of the
    channel or the pool, else what the strip type does.
    """
    if place.source is Source.CHANNELS:
        return None
    table = table_of(button, place.options.get(button))
    if isinstance(table, Mapping) and table.get(part) is not None:  # pyright: ignore[reportUnknownMemberType]
        return value_text(table[part])  # pyright: ignore[reportUnknownArgumentType]
    if place.strip == "custom":
        # a button of a custom channel does nothing unless it is told to
        return "off"
    options = place.options
    setup = default_setup(
        button,  # pyright: ignore[reportArgumentType]: a button option is named like its button
        place.strip,
        devices=place.show == DEVICES or bool(options.get("device") or options.get("choices")),
        profiles=bool(options.get("profiles")),
        launch=options.get("launch") is not None,
    )
    shown = getattr(setup, part)
    return describe_action(shown) if isinstance(shown, str) else value_text(shown)


BUTTON_TITLES = {"select": "Select", "rec": "Rec", "solo": "Solo"}

PLACE_HELP = {
    "label": "The top line of the LCD while slot {slot} shows `{show}`.",
    "color": "The backlight of the LCD while slot {slot} shows `{show}`.",
    "lit_when_idle": "Keeps the LCD of slot {slot} lit while `{show}` has nothing to control there.",
    "meter": (
        "What the LED meter shows while slot {slot} shows `{show}`: the level before or after the volume and Mute, "
        "or nothing."
    ),
    "encoder": "What the encoder does while slot {slot} shows an application of `{show}` without a channel.",
    "min_volume": "The volume, in percent, with the fader at the bottom while slot {slot} shows `{show}`.",
    "max_volume": "The volume, in percent, with the fader at the top while slot {slot} shows `{show}`.",
    "select": (
        'What the LED of Select shows while slot {slot} shows `{show}`. `press = "off"`: Select does nothing there.'
    ),
    "rec": "What the LED of Rec shows while slot {slot} shows `{show}`.",
    "solo": "What the LED of Solo shows while slot {slot} shows `{show}`.",
}
"""The help of the options of a place (see Writing help in `AGENTS.md`), before what unset means."""


def place_help(place: Origin, name: str, slot: int, value: str | None = None) -> str:
    """
    The help of an option of the place in `slot`: what it changes there, and what unset means; with `value`, the
    value it takes then (for a field without a placeholder, e.g. a switch).
    """
    text = PLACE_HELP.get(name, "")
    if name == "encoder" and place.show == DEVICES:
        text = "What the encoder does while slot {slot} shows a device of `{show}`."
    unset = f"{place.unset[:-1]}: `{value}`." if value else place.unset
    return " ".join(part for part in (text.format(slot=slot, show=place.show), unset) if part)
