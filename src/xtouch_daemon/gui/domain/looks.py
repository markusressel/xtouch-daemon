"""How the strips of a configuration look on the device: the label and color of each LCD, for the preview."""

from dataclasses import dataclass
from typing import Any

from xtouch_daemon import protocol
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config import STRIP_TYPES
from xtouch_daemon.gui.domain.document import ConfigDocument, Validation
from xtouch_daemon.gui.domain.schema import Kind, strip_options


@dataclass(frozen=True)
class StripLook:
    kind: str
    """The type of the strip; "?" for a strip without a valid type."""
    label: str
    """The top line of the LCD."""
    detail: str
    """What the strip controls, in a few words."""
    color: str
    """A color name of the configuration; "off" is a dark LCD."""
    configured: bool
    """False for the strips after the configured ones, which are `auto`."""
    problems: int


def _color(values: dict[str, Any], strip_type: str) -> str:
    color = next((option for option in strip_options(strip_type) if option.kind == Kind.COLOR), None)
    if color is None:
        return "off"
    value = values.get("color", color.default)
    # a color that is not one shows as the default (the strip shows the problem)
    return value if value in color.choices else color.default


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _names(value: Any) -> tuple[str, ...]:
    """The devices of a strip: one name, or a list of them."""
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def look(values: dict[str, Any], state: AudioState, aliases: dict[str, str]) -> tuple[str, str, str, str]:
    """The kind, label, detail and color of a strip with these options."""
    strip_type = values.get("type")
    if not isinstance(strip_type, str) or strip_type not in STRIP_TYPES:
        return "?", "", "no valid type", "off"
    color = _color(values, strip_type)
    label = _text(values.get("label"))
    match strip_type:
        case "output" | "input":
            names = _names(values.get("device"))
            direction = Direction(strip_type)
            if not names:
                device = state.device(direction, None)
                detail = f"the default {strip_type}" + (f": {device.description}" if device else "")
            else:
                # like the daemon: the default one of them, or the first one that is there
                there = state.devices_matching(direction, names)
                device = next((d for d in there if state.is_default(d)), next(iter(there), None))
                detail = " or ".join(names) + (f": {device.description}" if device else " (not there now)")
                if len(names) == 1 and device is not None:
                    detail = device.description
            if not label:
                # like the daemon: the start of the description of a device that is there
                label = device.description if device is not None and names else strip_type.capitalize()
        case "apps":
            match = values.get("match")
            detail = ", ".join(map(str, match)) if isinstance(match, list) and match else "no applications"
        case "auto":
            label = "auto"
            playing = [aliases.get(stream.app, stream.app) for stream in state.streams if stream.playing]
            detail = "the next application that plays" + (f", e.g. {playing[0]}" if playing else "")
        case "homeassistant":
            strip_id = _text(values.get("id")) or "strip_<position>"
            detail = f"entities of Home Assistant ({strip_id}), automations decide what it does"
        case _:
            detail = "a dark strip"
    return strip_type, label[: protocol.LCD_CELL_WIDTH], detail, color


def looks(document: ConfigDocument, validation: Validation, state: AudioState) -> tuple[StripLook, ...]:
    """How every strip of the device looks, the configured ones and the `auto` strips after them."""
    aliases = dict(document.aliases)
    result: list[StripLook] = []
    for index in range(protocol.STRIPS):
        configured = index < len(document.strips)
        values = document.strips[index].values if configured else {"type": "auto"}
        kind, label, detail, color = look(values, state, aliases)
        problems = len(validation.at("strip", index)) if configured else 0
        result.append(StripLook(kind, label, detail, color, configured, problems))
    return tuple(result)
