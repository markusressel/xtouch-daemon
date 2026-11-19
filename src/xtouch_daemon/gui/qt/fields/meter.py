"""
`meter` and `meter_point` of a strip as one choice: where the meter takes the level, or off. Unset, both take their
defaults (the meter on, at `behavior.meter_point`).
"""

from collections.abc import Callable
from typing import Any

from xtouch_daemon.config.values import METER_POINTS
from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.qt.fields.option_row import OptionRow

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
"""`meter` and `meter_point` as one choice (see `meter_row`)."""


def meter_row(
    get: Callable[[str], Any],
    put: Callable[[str, Any], None],
    default_point: Callable[[], str],
    link: str | None = None,
) -> OptionRow:
    """
    The row of the meter: `get(name)` reads `meter` or `meter_point`, `put(name, value)` sets one (None: unsets it),
    `default_point` is where the meter takes the level when neither is set.
    """

    def shown() -> str | None:
        if get("meter") is False:
            return METER_OFF
        point = get("meter_point")
        return None if point is None else str(point)

    def chosen(value: str | None) -> None:
        put("meter", False if value == METER_OFF else None)
        put("meter_point", None if value in (None, METER_OFF) else value)

    return OptionRow(METER, shown, chosen, placeholder=default_point, link=link)
