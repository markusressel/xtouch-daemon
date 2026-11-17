"""
The slots over time: presence, states and the resolver, with the stability rules (held slots, the dwell time). What
the daemon will run, driven by observations at given times instead of the sound server.
"""

from collections.abc import Mapping

from xtouch_daemon.slots.inputs import Observation, PoolMembers, Presence
from xtouch_daemon.slots.model import ABSENT_AFTER, AUTO, PEOPLE, Scene
from xtouch_daemon.slots.resolver import Inputs, Result, resolve
from xtouch_daemon.slots.states import Override, StateEngine, States

DWELL = 1.0
"""Seconds a slot keeps what it shows before it changes again."""
HOME = 30 * 24 * 3600.0
"""Seconds a person who left keeps their slot as their home, for when they come back (if it is free then)."""

type Homes = Mapping[str, tuple[int, float]]
"""Per person of `people`, their home slot and when they were last on it."""


def ordered_homes(scene: Scene) -> dict[str, int]:
    """The homes of `[pool.people] order`: from the rightmost slot where `auto` is the first candidate, leftwards."""
    stable = sorted((slot for slot, stack in scene.stacks.items() if stack[0].show == AUTO), reverse=True)
    return dict(zip(scene.pools[PEOPLE].order, stable, strict=False))


class Simulation:
    def __init__(
        self,
        scene: Scene,
        overrides: Mapping[str, Override] | None = None,
        mode_pick: str | None = None,
        absent_after: float = ABSENT_AFTER,
        dwell: float = DWELL,
        homes: Homes | None = None,
    ):
        """`homes` are those learned before (a restart), at times of this simulation's clock."""
        self.scene = scene
        self.presence = Presence(scene, absent_after)
        self.members = PoolMembers(scene, absent_after)
        self.engine = StateEngine(scene, overrides, mode_pick)
        self.dwell = dwell
        self.result: Result | None = None
        self.states: States | None = None
        self._changed: dict[int, float] = {}
        self._homes: dict[str, tuple[int, float]] = dict(homes or {})
        """The slot of each person of `people`, and when they were last on it."""
        self._ordered = ordered_homes(scene)

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
        self._homes = {person: (slot, at) for person, (slot, at) in self._homes.items() if now - at < HOME}
        # the order of the configuration over what was learned
        homes = {person: slot for person, (slot, _) in self._homes.items()} | self._ordered
        inputs = Inputs(self.states.values, present, pools, frozenset(held | dwelling), pins or {}, homes)
        result = resolve(self.scene, inputs, self.result)
        for slot, shown in result.slots.items():
            if shown.pool == PEOPLE and shown.member is not None:
                self._homes[shown.member] = (slot, now)
        for slot, shown in result.slots.items():
            if self.result is not None and self.result.slots[slot] != shown:
                self._changed[slot] = now
        self.result = result
        return result

    @property
    def homes(self) -> Homes:
        """The learned homes (to keep them across a restart)."""
        return dict(self._homes)

    def deadline(self) -> float | None:
        """When a delay or a dwell ends, if one is pending: then the slots need another step."""
        times = [self.engine.deadline(), self.presence.deadline(), self.members.deadline()]
        times += [since + self.dwell for since in self._changed.values()]
        return min((time for time in times if time is not None), default=None)
