"""
Simulate on the page Slots: what the slots would show with other modes, states and presence (a what-if), from the
resolver alone; nothing goes to the daemon. The grid of distinct outcomes picks such what-ifs.
"""

import dataclasses
from dataclasses import dataclass

from xtouch_daemon.config.slots import SlotsSetup
from xtouch_daemon.gui.domain.looks import DARK, StripFace, StripLook
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import SlotsState, SlotView, StateView
from xtouch_daemon.slots.model import AUTO, BUILT_IN, DEFAULT
from xtouch_daemon.slots.outcomes import Outcome, Situation, dimensions, simulate, states_for

SIMULATED = "what if"
"""The source of a state that is on in a simulation."""


@dataclass(frozen=True)
class WhatIf(Situation):
    """
    What Simulate shows: the mode, the states that are on, the channels and pools `flipped` (absent; the built-in
    pools: present, `auto`: an application plays), so many people in the call, applications that play and outputs
    and inputs without a channel. The daemon can run it too (`live.StartPreview`).
    """

    @classmethod
    def of(cls, outcome: Outcome) -> WhatIf:
        """The what-if of a row of the grid."""
        return cls(outcome.mode, frozenset(outcome.on), frozenset(outcome.flipped))

    def counted(self, people: int | None = None, apps: int | None = None, devices: int | None = None) -> WhatIf:
        """With so many people in the call, applications that play, or devices without a channel."""
        return dataclasses.replace(
            self,
            people=self.people if people is None else people,
            apps=self.apps if apps is None else apps,
            devices=self.devices if devices is None else devices,
        )

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
    """The built-in pools are empty unless flipped, the channels present: the button says what flipping does."""
    if name == AUTO:
        return f"{name} plays"
    return f"{name} fill" if name in BUILT_IN else f"{name} absent"


def simulated(setup: SlotsSetup, what_if: WhatIf) -> SlotsState:
    """The slots and states as the live view would tell them in the what-if."""
    scene = setup.scene
    result = simulate(scene, what_if.mode, what_if.on, what_if.flipped, what_if.people, what_if.apps, what_if.devices)
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
    waiting = {pool: tuple(str(member) for member in members) for pool, members in result.waiting.items()}
    return SlotsState(what_if.mode, None, views, states, waiting)


def simulated_faces(setup: SlotsSetup, slots: SlotsState) -> tuple[StripFace, ...]:
    """
    The strips with the label and color of what each slot would show, dark for nothing; an application or a person
    with their name.
    """
    faces: list[StripFace] = []
    for view in slots.slots[: protocol.STRIPS]:
        name = view.channel or view.pool or "-"
        strip = setup.strips.get((view.slot, view.candidate or 0, view.channel))
        member = view.member if view.channel is None else None
        label = member or getattr(strip, "label", None) or name
        color = getattr(strip, "color", "white") if name != "-" else "off"
        state = dataclasses.replace(DARK, color=color, text=(label[: protocol.LCD_CELL_WIDTH], SIMULATED[:7]))
        look = StripLook("slot", label, f"Would show {name}", color, printed=name)
        faces.append(StripFace(look, state, live=False, dimmed=color == "off"))
    return tuple(faces)
