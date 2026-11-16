"""
How the strips look on the device, for the preview: what a configuration makes of them (the label and color of each
LCD), or what the running daemon shows right now (its live view), and which of the two the preview shows per strip.
"""

from dataclasses import dataclass
from typing import Any

from xtouch_daemon import protocol
from xtouch_daemon.audio.model import AudioState, Device, Direction
from xtouch_daemon.config import STRIP_TYPES
from xtouch_daemon.gui.domain.document import ConfigDocument, Validation
from xtouch_daemon.gui.domain.schema import Kind, strip_options
from xtouch_daemon.live import Snapshot, StripState
from xtouch_daemon.protocol import RingMode


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


def _profile_label(profiles: Any, state: AudioState, device: Device | None) -> str:
    """The label of the profile of `profiles` the card of the device is in, "" for none."""
    card = state.card(device.card) if device is not None else None
    active = card.profile_named(card.profile) if card is not None else None
    if active is None or not isinstance(profiles, list):
        return ""
    return next(
        (
            _text(profile.get("label"))
            for profile in profiles
            if isinstance(profile, dict) and active.matches(str(profile.get("profile")))
        ),
        "",
    )


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
            # like the daemon: the label of the profile the card is in, else the label, else the start of the
            # description of a device that is there
            label = _profile_label(values.get("profiles"), state, device) or label
            if not label:
                label = device.description if device is not None and names else strip_type.capitalize()
        case "apps":
            match = values.get("match")
            detail = ", ".join(map(str, match)) if isinstance(match, list) and match else "no applications"
        case "auto":
            label = "auto"
            playing = [aliases.get(stream.app, stream.app) for stream in state.streams if stream.playing]
            detail = "the next application that plays" + (f", e.g. {playing[0]}" if playing else "")
        case "voip":
            count = values.get("count", 1)
            label = "voip"  # until a participant is there
            places = f"{count} strips" if isinstance(count, int) and count > 1 else "a strip"
            detail = f"participants of the voice chat, {places}, the select button pages"
        case "homeassistant":
            strip_id = _text(values.get("id")) or "strip_<position>"
            detail = f"entities of Home Assistant ({strip_id}), automations decide what it does"
        case _:
            detail = "a dark strip"
    return strip_type, label[: protocol.LCD_CELL_WIDTH], detail, color


def looks(document: ConfigDocument, validation: Validation, state: AudioState) -> tuple[StripLook, ...]:
    """
    How every strip of the device looks, the configured ones and the `auto` strips after them. An `inherit` strip of a
    layout looks like the strip of the default layout at its place.
    """
    aliases = dict(document.aliases)
    default = document.default_strips
    result: list[StripLook] = []
    for index in range(protocol.STRIPS):
        configured = index < len(document.strips)
        values = document.strips[index].values if configured else {"type": "auto"}
        if values.get("type") == "inherit":
            inherited = default[index].values if index < len(default) else {"type": "auto"}
            kind, label, detail, color = look(inherited, state, aliases)
            detail = f"like the default layout: {detail}"
        else:
            kind, label, detail, color = look(values, state, aliases)
        problems = len(validation.at("strip", index)) if configured else 0
        result.append(StripLook(kind, label, detail, color, configured, problems))
    return tuple(result)


SECOND_LINES = {"output": "100%", "input": "100%", "apps": "idle"}
"""What the second line of the LCD shows in the preview of a file, which knows no volumes."""
FILE_FADER = 0.7
"""Where the preview of a file puts the faders of strips that control something."""


@dataclass(frozen=True)
class StripFace:
    """What the preview paints for a strip: how the configuration describes it, and what its LCD, LEDs etc. show."""

    look: StripLook
    state: StripState
    live: bool
    """Whether `state` is what the device shows right now; otherwise it is what the configuration would show."""
    edited: bool
    """Whether the strip has unsaved changes: then `state` shows them, not the device."""
    dimmed: bool
    """Whether the strip is dark on the device most of the time (an `auto` strip waits for an application)."""


def file_state(look: StripLook) -> StripState:
    """What a strip shows going by its configuration alone: its label on its color, the fader somewhere up."""
    controls = look.kind not in ("empty", "?")
    return StripState(
        color=look.color,
        text=(look.label, SECOND_LINES.get(look.kind, "")),
        leds={button.name.lower(): "off" for button in protocol.Button},
        ring=8 if controls else 0,
        ring_mode="wrap",
        fader=FILE_FADER if controls else 0.0,
        touched=False,
        meter=0,
    )


def faces(looks: tuple[StripLook, ...], snapshot: Snapshot | None, edited: tuple[bool, ...]) -> tuple[StripFace, ...]:
    """
    The strips for the preview: live while the daemon tells what the device shows (`snapshot`), except the ones with
    unsaved changes, which show how they will look; without the daemon all of them as the configuration has them.
    """
    result: list[StripFace] = []
    for index, (strip_look, changed) in enumerate(zip(looks, edited, strict=True)):
        if snapshot is not None and not changed:
            result.append(StripFace(strip_look, snapshot.strips[index], live=True, edited=False, dimmed=False))
        else:
            dimmed = not strip_look.configured or strip_look.kind == "auto"
            result.append(StripFace(strip_look, file_state(strip_look), live=False, edited=changed, dimmed=dimmed))
    return tuple(result)


def ring_leds(position: int, mode: str) -> frozenset[int]:
    """The LEDs (1..RING_MAX, from the left) a ring lights for a position, like the device does in each mode."""
    if position <= 0:
        return frozenset()
    position = min(position, protocol.RING_MAX)
    center = (protocol.RING_MAX + 1) // 2
    ring_mode = RingMode[mode.upper()]
    if ring_mode == RingMode.DOT:
        lit = range(position, position + 1)
    elif ring_mode == RingMode.BOOST_CUT:
        lit = range(min(position, center), max(position, center) + 1)
    elif ring_mode == RingMode.WRAP:
        lit = range(1, position + 1)
    else:
        spread = min(position, center) - 1
        lit = range(center - spread, center + spread + 1)
    return frozenset(lit)


METER_LEDS = (0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 7, 8)
"""How many LEDs each level (0..METER_MAX) lights, as measured on the device."""


def meter_leds(level: int) -> int:
    """
    How many LEDs of the meter a level (0..METER_MAX) lights from the bottom: the 8th (red, at the top) is the clip
    LED, only METER_MAX lights it.
    """
    return METER_LEDS[max(0, min(protocol.METER_MAX, level))]
