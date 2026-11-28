"""
Simulate on the page Slots, as data for QML: the buttons of the states, and the what-ifs (a mode, states, channels and
pools to turn the other way, how many people and applications there are), in groups. The groups are objects that stay
(`WhatIfGroup`), each with a model of rows that stay while their values change, so a toggle that is clicked keeps its
focus and its place while its look changes.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.domain.simulate import Inputs, WhatIf, is_present, presence_tip, state_tip
from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.domain.states import ordered
from xtouch_daemon.gui.quick.models import KeyedListModel
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import SlotsState
from xtouch_daemon.slots.model import APPS, DEVICES, PEOPLE

SIMULATE_TIP = (
    "What the slots would show in other modes and states, with the changes, where the preview shows: in the GUI or on "
    "the device (Esc ends it)"
)
MAX_COUNT = 2 * protocol.STRIPS
"""The most people, applications or outputs a what-if can have."""


def state_rows(document: SlotsDocument, slots: SlotsState | None) -> list[tuple[str, dict[str, Any]]]:
    """
    A button per state, modes first: its label, or its name until the daemon tells the state; then what overrides it.
    `on` is -1 until the daemon tells it, then 0 or 1.
    """
    picked = slots.mode_pick if slots is not None else None
    states = {state.name: state for state in slots.states} if slots is not None else {}
    rows: list[tuple[str, dict[str, Any]]] = []
    for name in ordered(document.get(("state",), {})):
        state = states.get(name)
        label = str(document.get(("state", name, "label")) or name)
        override = "" if state is None or state.override == "auto" else f" ({state.override})"
        if picked == name:
            override = " (picked)"
        tip = f"{name}: {state.source or 'off'}" if state is not None else name
        rows.append(
            (
                name,
                {
                    "name": name,
                    "text": f"{label}{override}",
                    "on": -1 if state is None else int(state.value),
                    "tip": f"{tip}\n\nClick for its override, or to simulate it the other way.",
                },
            )
        )
    return rows


class WhatIfGroup(QObject):
    """A group of what-ifs (Mode, States, Channels, Pools): its title over its controls."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, title: str, parent: QObject) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self._title = title
        self._items = KeyedListModel(self)

    @pyqtProperty(str, constant=True)
    def title(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._title

    @pyqtProperty(QObject, constant=True)
    def items(self) -> KeyedListModel:  # pyright: ignore[reportRedeclaration]
        return self._items

    @pyqtProperty(bool, notify=changed)
    def shown(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return bool(self._items.rows)

    def show(self, rows: list[tuple[str, dict[str, Any]]]) -> None:
        was = self.shown
        self._items.show(rows)
        if was != self.shown:
            self.changed.emit()


def toggle_row(what_if: WhatIf, start: WhatIf, name: str, flip: bool) -> tuple[str, dict[str, Any]]:
    """
    A state (on or off), or with `flip` the presence of a channel or pool: a dot says which it is in the what-if, a
    frame in the accent color that it differs from reality (`checked`).
    """
    flipped = name in (what_if.flipped if flip else what_if.on)
    lit = is_present(name, flipped) if flip else flipped
    return (
        f"{'present' if flip else 'state'}:{name}",
        {
            "kind": "toggle",
            "name": name,
            "flip": flip,
            "lit": lit,
            "checked": what_if.differs(start, name, flip),
            "tip": presence_tip(name, flipped) if flip else state_tip(name, flipped),
        },
    )


def what_if_rows(inputs: Inputs, what_if: WhatIf, start: WhatIf) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """The rows of the groups of the what-ifs, by the title of the group."""
    mode = (
        "mode",
        {"kind": "mode", "name": "mode", "modes": list(inputs.modes), "current": what_if.mode, "tip": "The mode"},
    )
    counts: dict[str, tuple[int, str, Callable[[int], WhatIf]]] = {
        PEOPLE: (what_if.people, "people in the voice chat", lambda n: what_if.counted(people=n)),
        APPS: (what_if.apps, "applications that play", lambda n: what_if.counted(apps=n)),
    }
    if DEVICES in inputs.presence:
        counts[DEVICES] = (what_if.devices, "outputs without a channel", lambda n: what_if.counted(devices=n))
    pools: list[tuple[str, dict[str, Any]]] = [
        (
            f"count:{name}",
            {
                "kind": "count",
                "name": name,
                "value": value,
                "lit": bool(value),
                "max": MAX_COUNT,
                "tip": f"How many {what}; 0: the pool {name} is empty",
            },
        )
        for name, (value, what, _) in counts.items()
    ]
    pools += [
        toggle_row(what_if, start, name, True) for name in inputs.presence if name in inputs.pools - counts.keys()
    ]
    return {
        "Mode": [mode],
        "States": [toggle_row(what_if, start, name, False) for name in inputs.states],
        "Channels": [toggle_row(what_if, start, name, True) for name in inputs.channels],
        "Pools": pools,
    }


def counted(what_if: WhatIf, name: str, value: int) -> WhatIf:
    """The what-if with so many people, applications or outputs without a channel."""
    return what_if.counted(**{{PEOPLE: "people", APPS: "apps", DEVICES: "devices"}[name]: value})


def with_mode(what_if: WhatIf, mode: str) -> WhatIf:
    return dataclasses.replace(what_if, mode=mode)
