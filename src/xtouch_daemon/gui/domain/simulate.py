"""
Simulate on the page Slots: what the slots would show with other modes, states and presence (a what-if). The daemon
runs it where the preview shows (`live.StartPreview`): on a virtual twin, or on the device.
"""

import dataclasses
from dataclasses import dataclass

from xtouch_daemon.config.slots import SlotsSetup
from xtouch_daemon.live.messages import SlotsState
from xtouch_daemon.slots.model import AUTO, BUILT_IN, DEFAULT
from xtouch_daemon.slots.outcomes import Situation, dimensions


@dataclass(frozen=True)
class WhatIf(Situation):
    """
    What Simulate shows: the mode, the states that are on, the channels and pools `flipped` (absent; the built-in
    pools: present, `auto`: an application plays), so many people in the call, applications that play and outputs
    and inputs without a channel. The daemon can run it too (`live.StartPreview`).
    """

    @classmethod
    def of_live(cls, slots: SlotsState) -> WhatIf:
        """The mode and the states that are on as the daemon tells them, the rest as `Simulate` starts it."""
        on = frozenset(state.name for state in slots.states if state.value and not state.mode)
        return cls(mode=slots.mode, on=on)

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
    pools: frozenset[str] = frozenset()
    """The names of `presence` that are pools; the others are channels."""

    @classmethod
    def of(cls, setup: SlotsSetup) -> Inputs:
        scene = setup.scene
        states, presence = dimensions(scene)
        pools = frozenset((*BUILT_IN, *scene.apps_pools, *scene.people_pools))
        return cls((DEFAULT, *scene.modes), states, presence, pools & frozenset(presence))

    @property
    def channels(self) -> tuple[str, ...]:
        """The channels whose presence the stacks ask about."""
        return tuple(name for name in self.presence if name not in self.pools)


def is_present(name: str, flipped: bool) -> bool:
    """
    Whether a channel or pool of the what-if is there: the channels are present unless flipped, the built-in pools
    empty unless flipped (`auto`: no application plays for it).
    """
    return flipped if name in BUILT_IN or name == AUTO else not flipped


def presence_tip(name: str, flipped: bool) -> str:
    """What the toggle of a channel or pool shows now, and what a click makes of it."""
    present = is_present(name, flipped)
    if name == AUTO:
        now, then = ("An application plays", "none") if present else ("No application plays", "one does")
        return f"{now} for auto. Click: {then}."
    if name in BUILT_IN:
        now, then = ("has members", "it is empty") if present else ("is empty", "it has members")
        return f"The pool {name} {now}. Click: {then}."
    return f"{name} is {'present' if present else 'absent'}. Click: {'absent' if present else 'present'}."


def state_tip(name: str, on: bool) -> str:
    """What the toggle of a state shows now, and what a click makes of it."""
    return f"{name} is {'on' if on else 'off'}. Click: {'off' if on else 'on'}."
