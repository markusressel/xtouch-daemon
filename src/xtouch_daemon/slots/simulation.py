"""
The slots over time: presence, states and the resolver, with the stability rules (held slots, the dwell time). What
the daemon will run, driven by observations at given times instead of the sound server.
"""

from collections.abc import Mapping

from xtouch_daemon.slots.inputs import Observation, PoolMembers, Presence
from xtouch_daemon.slots.model import ABSENT_AFTER, Scene
from xtouch_daemon.slots.resolver import Inputs, Result, resolve
from xtouch_daemon.slots.states import Override, StateEngine, States

DWELL = 1.0
"""Seconds a slot keeps what it shows before it changes again."""
KNOWN = 30 * 24 * 3600.0
"""Seconds the order of the people keeps someone who was not there."""

type Known = Mapping[str, float]
"""The people seen in the voice chat, in the order they were first seen, and when last."""


class Simulation:
    def __init__(
        self,
        scene: Scene,
        overrides: Mapping[str, Override] | None = None,
        mode_pick: str | None = None,
        absent_after: float = ABSENT_AFTER,
        dwell: float = DWELL,
        known: Known | None = None,
    ):
        """`known` are the people seen before (a restart), at times of this simulation's clock."""
        self.scene = scene
        self.presence = Presence(scene, absent_after)
        self.members = PoolMembers(scene, absent_after)
        self.engine = StateEngine(scene, overrides, mode_pick)
        self.dwell = dwell
        self.result: Result | None = None
        self.states: States | None = None
        self._changed: dict[int, float] = {}
        self._known: dict[str, float] = dict(known or {})

    def step(
        self,
        observation: Observation,
        now: float,
        held: frozenset[int] = frozenset(),
        pins: Mapping[int, str] | None = None,
    ) -> Result:
        """
        What the slots show at `now`: `held` are the slots under a finger (or a held button, or a touchless fader the
        user just moved), `pins` the applications pinned with the `pick` encoder.
        """
        present = self.presence.update(observation, now)
        self.states = self.engine.update(observation, present, now)
        self._changed = {slot: since for slot, since in self._changed.items() if now - since < self.dwell}
        dwelling = set(self._changed)
        pools = self.members.update(observation, now)
        for person in observation.people:
            self._known[person] = now
        self._known = {person: at for person, at in self._known.items() if now - at < KNOWN}
        inputs = Inputs(self.states.values, present, pools, frozenset(held | dwelling), pins or {}, self.order)
        result = resolve(self.scene, inputs, self.result)
        for slot, shown in result.slots.items():
            if self.result is not None and self.result.slots[slot] != shown:
                self._changed[slot] = now
        self.result = result
        return result

    @property
    def order(self) -> tuple[str, ...]:
        """The order of the people: `[pool.people] order`, then the others in the order they were first seen."""
        configured = self.scene.people.order
        return (*configured, *(person for person in self._known if person not in configured))

    @property
    def known(self) -> Known:
        """The people seen (to keep them across a restart)."""
        return dict(self._known)

    def deadline(self) -> float | None:
        """When a delay or a dwell ends, if one is pending: then the slots need another step."""
        times = [self.engine.deadline(), self.presence.deadline(), self.members.deadline()]
        times += [since + self.dwell for since in self._changed.values()]
        return min((time for time in times if time is not None), default=None)
