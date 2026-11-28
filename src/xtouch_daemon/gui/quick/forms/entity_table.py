"""
What the options of a table with an entity of Home Assistant take while unset (a part bound to an entity: `entity`,
`attribute`, `min`, ...; a press that calls a service: `service`, `entity`, `data`), and where a number of them starts
once it is set. The domain of the entity decides: `default: 255, of a light`.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from xtouch_daemon.gui.domain.entities import value_placeholder
from xtouch_daemon.gui.quick.forms.binding import DEFAULT_ENCODER_STEP
from xtouch_daemon.homeassistant.states import EntityState

PLACEHOLDERS: dict[str, str] = {
    "step": "behavior.encoder_step % of the range",
    "push": "none: a push does nothing",
}
"""What an unset option does, where its default is no value and the entity does not change it."""


def sets_value(model: type[BaseModel] | None) -> bool:
    """A value that a fader or an encoder sets (`EntityValueBinding`): the domain decides what is unset."""
    return model is not None and "min" in model.model_fields and "service" in model.model_fields


def placeholder(
    name: str, default: object, marker: str, sets: bool, table: Mapping[str, Any], entity: EntityState | None
) -> str | None:
    """What the unset option `name` of a table takes, None for no placeholder of its own."""
    if name in PLACEHOLDERS:
        return PLACEHOLDERS[name]
    match name:
        case "entity":
            return "e.g. light.desk" if marker == "entity" else "default: none"
        case "service":
            if not sets:
                return "e.g. light.toggle"
        case "data":
            if not sets:
                return "none"
        case "attribute":
            if not sets:
                return "default: none: the state"
        case _:
            pass
    if not sets or default is not None:
        return None
    # a text says "default:" itself, a number and the data get it from their row
    before = "default: " if name in ("attribute", "service") else ""
    return before + (value_placeholder(name, table, entity) or "")


def start_of(name: str, table: Mapping[str, Any], sets: bool, entity: EntityState | None) -> float:
    """Where a number starts once it is set: in the range by the domain of the entity."""

    def number(key: str, fallback: float) -> float:
        value = table.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        if not sets:
            return fallback
        try:
            return float((value_placeholder(key, table, entity) or "").split(",")[0])
        except ValueError:
            return fallback

    low, high = number("min", 0), number("max", 100)
    if high <= low:
        low, high = 0, 100
    if name == "step":
        return (high - low) * DEFAULT_ENCODER_STEP / 100
    return high if name == "max" else low
