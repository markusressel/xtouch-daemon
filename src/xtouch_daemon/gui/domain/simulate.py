"""
Simulate on the page Device: what the slots would show with other modes, states and presence (a what-if), from the
resolver alone; nothing goes to the daemon. The grid of distinct outcomes picks such what-ifs.
"""

import dataclasses
from dataclasses import dataclass, field

from xtouch_daemon.config.slots import SlotsSetup
from xtouch_daemon.gui.domain.looks import DARK, StripFace, StripLook
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import SlotsState, SlotView, StateView
from xtouch_daemon.slots.model import AUTO, DEFAULT
from xtouch_daemon.slots.outcomes import Outcome, dimensions, simulate, states_for

SIMULATED = "what if"
"""The source of a state that is on in a simulation."""


@dataclass(frozen=True)
class WhatIf:
    mode: str = DEFAULT
    on: frozenset[str] = field(default_factory=frozenset[str])
    """The states that are on."""
    flipped: frozenset[str] = field(default_factory=frozenset[str])
    """The channels and pools that are absent; `auto`: an application plays."""

    @classmethod
    def of(cls, outcome: Outcome) -> WhatIf:
        """The what-if of a row of the grid."""
        return cls(outcome.mode, frozenset(outcome.on), frozenset(outcome.flipped))

    def toggled(self, name: str, flip: bool) -> WhatIf:
        """With the state `name` (or, with `flip`, the presence of the channel or pool) the other way."""
        if flip:
            return dataclasses.replace(self, flipped=self.flipped ^ {name})
        return dataclasses.replace(self, on=self.on ^ {name})


@dataclass(frozen=True)
class Inputs:
    """What a what-if can change in a configuration: its modes, the states and the presence the stacks ask about."""

    modes: tuple[str, ...]
    states: tuple[str, ...]
    presence: tuple[str, ...]

    @classmethod
    def of(cls, setup: SlotsSetup) -> Inputs:
        states, presence = dimensions(setup.scene)
        return cls((DEFAULT, *setup.scene.modes), states, presence)


def presence_text(name: str) -> str:
    """`auto` is empty unless flipped, other channels present: the button says what flipping does."""
    return f"{name} plays" if name == AUTO else f"{name} absent"


def simulated(setup: SlotsSetup, what_if: WhatIf) -> SlotsState:
    """The slots and states as the live view would tell them in the what-if."""
    scene = setup.scene
    result = simulate(scene, what_if.mode, what_if.on, what_if.flipped)
    views = tuple(
        SlotView(
            slot,
            shown.candidate,
            shown.channel,
            shown.pool,
            str(shown.member) if shown.member is not None else None,
            result.why[slot],
        )
        for slot, shown in result.slots.items()
    )
    values = states_for(scene, what_if.mode, what_if.on)
    states = tuple(
        StateView(name, values[name], config.mode, None, SIMULATED if values[name] else None, "auto")
        for name, config in scene.states.items()
    )
    return SlotsState(what_if.mode, None, views, states, {})


def simulated_faces(setup: SlotsSetup, slots: SlotsState) -> tuple[StripFace, ...]:
    """The strips with the label and color of what each slot would show, dark for nothing."""
    faces: list[StripFace] = []
    for view in slots.slots[: protocol.STRIPS]:
        name = view.channel or view.pool or "-"
        strip = setup.strips.get((view.slot, view.candidate or 0, view.channel))
        label = getattr(strip, "label", None) or name
        color = getattr(strip, "color", "white") if name != "-" else "off"
        state = dataclasses.replace(DARK, color=color, text=(label[: protocol.LCD_CELL_WIDTH], SIMULATED[:7]))
        look = StripLook("slot", label, f"Would show {name}", color, printed=name)
        faces.append(StripFace(look, state, live=False, dimmed=color == "off"))
    return tuple(faces)
