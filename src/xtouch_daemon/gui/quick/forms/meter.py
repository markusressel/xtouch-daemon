"""
`meter` and `meter_point` of a strip as one choice: where the meter takes the level, or off. Unset, both take their
defaults (the meter on, at `behavior.meter_point`). On a channel, the meter can be bound too: to Home Assistant or to a
program of your own (`meter = { watch = [...] }`, `{ poll = [...] }`).
"""

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

from xtouch_daemon.config.bindings import HOME_ASSISTANT, METER_PARTS, LevelBinding
from xtouch_daemon.config.values import METER_POINTS
from xtouch_daemon.gui.domain.schema import Kind, Option, options

METER_OFF = "off"
METER = Option(
    "meter",
    Kind.CHOICE,
    "What the LED meter shows: the level before the volume and Mute of the strip, or after them, or nothing. "
    "Needs `behavior.meters`; by default `behavior.meter_point`.",
    None,
    False,
    choices=(*METER_POINTS.meanings, METER_OFF),
    meanings=(*METER_POINTS.meanings.items(), (METER_OFF, "The meter stays dark.")),
)
"""`meter` and `meter_point` as one choice, as at a place: bindings belong to the channel."""
BOUND_METER = dataclasses.replace(
    METER,
    kind=Kind.BINDING,
    help=METER.help + " A `watch` or a `poll` makes it show each number it prints, from `min` to `max`.",
    base=Kind.CHOICE,
    meanings=(*METER.meanings, *METER_PARTS.meanings.items()),
    # a level may be below 0, e.g. in dB, and fine
    columns=tuple(
        dataclasses.replace(column, signed=True) if column.kind == Kind.NUMBER else column
        for column in options(LevelBinding)
    ),
    home_assistant=True,
    binding=" ".join((LevelBinding.__doc__ or "").split()),
)
"""The meter of a channel: one choice, or bound to Home Assistant or a program."""


def shown(get: Callable[[str], Any]) -> object:
    """The value of the row: `get(name)` reads `meter` or `meter_point`."""
    meter = get("meter")
    if meter is False:
        return METER_OFF
    if meter == HOME_ASSISTANT or isinstance(meter, Mapping):
        return meter
    point = get("meter_point")
    return None if point is None else str(point)


def chosen(put: Callable[[str, Any], None], value: object) -> None:
    """Writes the value of the row: `put(name, value)` sets `meter` or `meter_point` (None unsets it)."""
    bound = value == HOME_ASSISTANT or isinstance(value, Mapping)
    put("meter", False if value == METER_OFF else value if bound else None)
    put("meter_point", None if value is None or value == METER_OFF or bound else value)
