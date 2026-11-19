"""
How the strips look in the drawing of the device: what the running daemon shows right now (its live view), with what
each slot shows printed under it; dark while there is no daemon to tell, or no device.
"""

from dataclasses import dataclass

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import RingMode
from xtouch_daemon.live.messages import SlotsState, SlotView, Snapshot, StripState, TwinView


@dataclass(frozen=True)
class StripLook:
    kind: str
    """What the strip is, for its tip: "slot"; "?" while nobody tells."""
    label: str
    """The top line of the LCD."""
    detail: str
    """What the strip controls, in a few words."""
    color: str
    """A color name of the configuration; "off" is a dark LCD."""
    configured: bool = True
    """False while the strip shows nothing the GUI knows of: it is drawn fainter."""
    printed: str = ""
    """What is printed under the strip instead of its kind, "" for the kind."""


@dataclass(frozen=True)
class StripFace:
    """What the drawing paints for a strip: what it is, and what its LCD, LEDs etc. show."""

    look: StripLook
    state: StripState
    live: bool
    """Whether `state` is what the device shows right now."""
    dimmed: bool = False
    """Whether the strip is dark on the device."""


DARK = StripState(
    color="off",
    text=("", ""),
    leds={button.name.lower(): "off" for button in protocol.Button},
    ring=0,
    ring_mode="wrap",
    fader=0.0,
    touched=False,
    meter=0,
)
"""A strip while nobody tells what it shows."""
UNKNOWN = StripFace(StripLook("?", "", "No daemon tells what it shows.", "off", False), DARK, False)
AWAY = StripFace(StripLook("?", "", "The device is not connected.", "off", False), DARK, False)
"""A strip while the daemon runs without the device: nothing to show, like the device that is not there."""


def shown(view: SlotView) -> str:
    """What a slot shows, in a few words: `firefox via auto`, `out`, `nothing`."""
    what = view.member or view.channel or "nothing"
    via = f" via {view.pool}" if view.pool is not None and view.member is not None else ""
    return f"{what}{via}"


def device_faces(snapshot: Snapshot | None) -> tuple[StripFace, ...]:
    """
    The strips as the device shows them right now, with what each slot shows; dark without the daemon, and while the
    device is not connected.
    """
    if snapshot is None:
        return (UNKNOWN,) * protocol.STRIPS
    if not snapshot.device:
        return (AWAY,) * protocol.STRIPS
    return faces_of(snapshot.strips, snapshot.slots)


def twin_faces(view: TwinView) -> tuple[StripFace, ...]:
    """The strips of a virtual twin as it shows them right now, with what each slot shows."""
    return faces_of(view.strips, view.slots)


def faces_of(strips: tuple[StripState, ...], slots: SlotsState | None) -> tuple[StripFace, ...]:
    """The strips as a mirror of a device shows them, with what each slot of `slots` shows."""
    views = slots.slots if slots is not None else ()
    result: list[StripFace] = []
    for index, state in enumerate(strips[: protocol.STRIPS]):
        view = next((view for view in views if view.slot == index + 1), None)
        printed = (view.channel or view.pool or "-") if view is not None else ""
        detail = f"Shows {shown(view)}" if view is not None else ""
        look = StripLook("slot", state.text[0], detail, state.color, printed=printed)
        result.append(StripFace(look, state, live=True, dimmed=state.color == "off"))
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
