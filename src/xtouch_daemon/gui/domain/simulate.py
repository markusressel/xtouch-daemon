"""
Simulate on the page Slots: what the slots would show with other modes, states and presence (a what-if). The daemon
runs it on a virtual twin (`live.StartTwin`), and on the device too with Try on the device (`live.StartPreview`).
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

    @classmethod
    def of(cls, setup: SlotsSetup) -> Inputs:
        states, presence = dimensions(setup.scene)
        return cls((DEFAULT, *setup.scene.modes), states, presence)


def presence_text(name: str) -> str:
    """The built-in pools are empty unless flipped, the channels present: the button says what flipping does."""
    if name == AUTO:
        return f"{name} plays"
    return f"{name} fill" if name in BUILT_IN else f"{name} absent"
