"""
Where the window shows a problem of the configuration: the page, and the channel, state or slot on it.
"""

from dataclasses import dataclass

from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain.schema import SECTIONS
from xtouch_daemon.hardware import protocol


@dataclass(frozen=True)
class Place:
    """A page of the window (`MainWindow.show_page()`), with what to pick on it."""

    page: str
    """A page of the rail ("slots", "channels", "states") or of the settings (a section, "aliases")."""
    channel: tuple[str, str] | None = None
    """On the page Channels: `("channel", <id>)` or a built-in pool (`("pool", <id>)`)."""
    state: str | None = None
    """On the page States: the state."""
    slot: int | None = None
    """On the page Slots: the slot (1 for the leftmost one), picked on the drawing of the device."""


def place_of(problem: Problem) -> Place | None:
    """
    Where `problem` is shown; for a problem of the whole configuration (e.g. channels of Home Assistant without
    `[mqtt]`), the last section its message names, None when it names none.
    """
    match problem.path:
        case ("channel", str(name), *_):
            return Place("channels", channel=("channel", name))
        case ("pool", "auto" | "apps" | "people" as pool, *_):
            return Place("channels", channel=("pool", pool))
        case ("people", *_):
            # today's [pool.people]: its message is there
            return Place("channels", channel=("pool", "people"))
        case ("state", str(name), *_):
            return Place("states", state=name)
        case ("slots" | "controls", str(slot), *_) if slot.isdigit() and 1 <= int(slot) <= protocol.STRIPS:
            return Place("slots", slot=int(slot))
        case ("slots" | "controls", *_):
            return Place("slots")
        case (str(name), *_) if name in SECTIONS or name == "aliases":
            return Place(name)
        case _:
            named = [name for name in SECTIONS if f"[{name}]" in problem.message]
            return Place(named[-1]) if named else None
