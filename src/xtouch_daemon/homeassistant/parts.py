"""
How the state of an entity becomes what a part shows (`line_of()`): a text for the LCD, a color name, a number for
the meter, a word for an LED, or whether a channel is there. These are lines as a `watch` prints them, so the parts
show them as they show those. And the value of an entity a fader or an encoder sets (`value_of()`, `range_of()`).
"""

import colorsys
import math
from typing import Any, Literal, get_args

from xtouch_daemon.config.bindings import EntityValueBinding
from xtouch_daemon.config.values import ColorName
from xtouch_daemon.homeassistant.domains import DomainValue, domain_of, domain_value
from xtouch_daemon.homeassistant.states import EntityState

LineKind = Literal["text", "color", "level", "led", "present"]
"""What a part makes of an entity: the LCD a text, `color` a color name, the meter a number, an LED, `present`."""
LIT_STATES = frozenset({"on", "open", "playing", "home"})
"""The states that light an LED, besides the words of a `watch` (`1`, `true`, `yes`; `flash` flashes it)."""
PRESENT = "present"
"""The line of `present` for an entity that is there; an empty line is absent."""
_COLORS: frozenset[str] = frozenset(get_args(ColorName))
_UNITS_CLOSE = ("%", "°")
"""Units the LCD shows right after the number (`45%`, `21.5°C`); the others after a space (`3.2 kW`)."""


def number_text(number: float) -> str:
    """A number for the LCD: whole from 100 on, one decimal from 10 on, else two; no trailing zeros (`21.5`)."""
    digits = 0 if abs(number) >= 100 else 1 if abs(number) >= 10 else 2
    text = f"{round(number, digits):.{digits}f}"
    if digits:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _number(value: object) -> float | None:
    """The number of a value of an entity: a number, or a text that is one; None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def raw_value(entity: EntityState, attribute: str | None) -> Any:
    """The state of an entity, or one of its attributes (None for one it does not have)."""
    return entity.attributes.get(attribute) if attribute is not None else entity.state


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if (number := _number(value)) is not None and not isinstance(value, str):
        return number_text(number)
    if isinstance(value, list | tuple):
        return ", ".join(_text(item) for item in value)  # pyright: ignore[reportUnknownVariableType]
    return str(value)


def text_of(entity: EntityState, attribute: str | None) -> str | None:
    """
    The LCD's text of an entity: its state (a number shortened, with its unit) or an attribute; None while it is not
    known.
    """
    value = raw_value(entity, attribute)
    if value is None or (attribute is None and not entity.known):
        return None
    if attribute is None and (number := _number(value)) is not None:
        unit = entity.attributes.get("unit_of_measurement")
        text = number_text(number)
        if isinstance(unit, str) and unit:
            return f"{text}{unit}" if unit.startswith(_UNITS_CLOSE) else f"{text} {unit}"
        return text
    return _text(value)


def nearest_color(red: float, green: float, blue: float) -> ColorName:
    """
    The color of the LCD nearest to a color of red, green and blue (0..255): white for one with little color, `off`
    for black, else the channels that are at least half of the strongest.
    """
    strongest = max(red, green, blue)
    if strongest <= 0:
        return "off"
    if (strongest - min(red, green, blue)) / strongest < 0.25:
        return "white"
    lit = (red >= strongest / 2, green >= strongest / 2, blue >= strongest / 2)
    names: dict[tuple[bool, bool, bool], ColorName] = {
        (True, False, False): "red",
        (False, True, False): "green",
        (False, False, True): "blue",
        (True, True, False): "yellow",
        (True, False, True): "magenta",
        (False, True, True): "cyan",
    }
    return names.get(lit, "white")


def _color_of_value(value: object) -> ColorName | None:
    """A color of a value: a color name (any case), or a list of red, green and blue."""
    if isinstance(value, str):
        word = value.strip().lower()
        return word if word in _COLORS else None  # type: ignore[return-value]
    if isinstance(value, list | tuple) and len(value) == 3:  # pyright: ignore[reportUnknownArgumentType]
        channels = [_number(channel) for channel in value]  # pyright: ignore[reportUnknownVariableType]
        if all(channel is not None for channel in channels):
            red, green, blue = (channel or 0.0 for channel in channels)
            return nearest_color(red, green, blue)
    return None


def color_of(entity: EntityState, attribute: str | None) -> ColorName | None:
    """
    The color of an entity: an attribute that is a color (a name, or red, green and blue); a light's color (`off`
    while it is off, white without a color of its own); else a state that is a color name. None for none.
    """
    if attribute is not None:
        return _color_of_value(entity.attributes.get(attribute))
    if domain_of(entity.entity_id) == "light" and entity.known:
        if entity.state == "off":
            return "off"
        if (rgb := _color_of_value(entity.attributes.get("rgb_color"))) is not None:
            return rgb
        hs = entity.attributes.get("hs_color")
        if isinstance(hs, list | tuple) and len(hs) == 2:  # pyright: ignore[reportUnknownArgumentType]
            hue, saturation = (_number(part) for part in hs)  # pyright: ignore[reportUnknownVariableType]
            if hue is not None and saturation is not None:
                red, green, blue = colorsys.hsv_to_rgb(hue / 360, saturation / 100, 1.0)
                return nearest_color(red * 255, green * 255, blue * 255)
        return "white"
    return _color_of_value(entity.state) if entity.known else None


def led_of(entity: EntityState, attribute: str | None) -> str | None:
    """The word of an LED for an entity: `on` for the states of LIT_STATES and for true, else the value as it is."""
    value = raw_value(entity, attribute)
    if value is None or (attribute is None and not entity.known):
        return None
    if isinstance(value, bool):
        return "on" if value else "off"
    word = str(value).strip().lower()
    return "on" if word in LIT_STATES else word


def line_of(entity: EntityState | None, attribute: str | None, kind: LineKind, known: bool) -> str | None:
    """
    The line of an entity for a part of the kind; None while it is not known. `present` is absent (an empty line) for
    an entity that is `unavailable` or `unknown`, or that Home Assistant does not have; while the states were never in
    (`known`), it is not known either.
    """
    if kind == "present":
        if entity is None or not entity.known or raw_value(entity, attribute) is None:
            return "" if known else None
        return PRESENT
    if entity is None:
        return None
    match kind:
        case "text":
            return text_of(entity, attribute)
        case "color":
            return color_of(entity, attribute)
        case "led":
            return led_of(entity, attribute)
        case "level":
            value = _number(raw_value(entity, attribute)) if entity.known else None
            return f"{value:f}" if value is not None else None


def range_of(entity: EntityState | None, binding: EntityValueBinding) -> tuple[float, float]:
    """
    The range of the value of an entity binding: its `min` and `max`; else the entity's (a `number`), else that of its
    domain, else 0..100.
    """
    domain = domain_value(binding.entity, binding.attribute)
    low = float(domain.min) if domain is not None else 0.0
    high = float(domain.max) if domain is not None else 100.0
    if entity is not None and domain is not None and domain.ranged:
        if (own := _number(entity.attributes.get("min"))) is not None:
            low = own
        if (own := _number(entity.attributes.get("max"))) is not None:
            high = own
    low = binding.min if binding.min is not None else low
    high = binding.max if binding.max is not None else high
    return (low, high) if high > low else (low, low + 1)


def value_of(entity: EntityState | None, binding: EntityValueBinding) -> float | None:
    """The value of an entity a fader or an encoder sets; None while it is not known."""
    if entity is None or not entity.known:
        return None
    domain: DomainValue | None = domain_value(binding.entity, binding.attribute)
    attribute = binding.attribute if binding.attribute is not None else domain.attribute if domain else None
    value = _number(raw_value(entity, attribute))
    if value is None and domain is not None and domain.off_is_min and entity.state == "off":
        return range_of(entity, binding)[0]
    return value
