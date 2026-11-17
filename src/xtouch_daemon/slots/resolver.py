"""
What each of the 8 slots shows: fixed slots first, then the channels by rank, then the pools. Pure: the same inputs
give the same result; only members of `auto` and `people` look at the previous one, to keep their slots.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from xtouch_daemon.hardware import protocol
from xtouch_daemon.slots.inputs import Observation, excluded, owner_of, people_without_channel, pool_present
from xtouch_daemon.slots.model import AUTO, PEOPLE, Candidate, Scene

SLOTS = range(1, protocol.STRIPS + 1)


@dataclass(frozen=True)
class Shown:
    """What a slot shows: a channel, a member of a pool (an application, a person or a channel), or nothing."""

    candidate: int | None
    """The index of the candidate in the slot's stack; None for nothing at all."""
    channel: str | None = None
    """The channel it shows: of a channel candidate, or a channel that is a member of a pool."""
    pool: str | None = None
    member: str | None = None
    """The application or person of a pool, None for an empty pool (a dark slot)."""

    def __str__(self) -> str:
        if self.pool is None:
            return self.channel or "-"
        if self.member is None:
            return self.pool
        return f"{self.pool}:{self.member}"


@dataclass(frozen=True)
class Inputs:
    """What the resolver decides from."""

    states: Mapping[str, bool]
    present: frozenset[str]
    """The channels that are present."""
    observation: Observation = field(default_factory=Observation)
    """The applications and people the pools hand out."""
    fixed: frozenset[int] = frozenset()
    """Slots that keep what they show: held by a finger or a button, or within their dwell time."""
    pins: Mapping[int, str] = field(default_factory=dict)
    """Applications pinned to `auto` slots with the `pick` encoder."""
    homes: Mapping[str, int] = field(default_factory=dict)
    """The slot each person of `people` had last (for a while): they get it again when they come back."""


@dataclass(frozen=True)
class Result:
    slots: Mapping[int, Shown]
    waiting: Mapping[str, tuple[str, ...]]
    """Per pool, the members that got no slot."""
    why: Mapping[int, tuple[str, ...]]
    """Per slot, why not each candidate above the one it shows, and why that one."""

    def slot_of(self, channel: str) -> int | None:
        return next((slot for slot, shown in self.slots.items() if shown.channel == channel), None)


def resolve(scene: Scene, inputs: Inputs, previous: Result | None = None) -> Result:
    resolver = _Resolver(scene, inputs, previous)
    return resolver.run()


class _Resolver:
    def __init__(self, scene: Scene, inputs: Inputs, previous: Result | None):
        self.scene = scene
        self.inputs = inputs
        self.previous = previous
        self.why: dict[int, list[str]] = {slot: [] for slot in SLOTS}

    def present(self, own: str | None, target: str | None) -> bool:
        name = target if target is not None else own
        assert name is not None
        if name in self.scene.pools:
            return pool_present(self.scene, name, self.inputs.observation, self.inputs.present)
        return name in self.inputs.present

    def holds(self, candidate: Candidate) -> bool:
        if candidate.when is None:
            return True
        return candidate.when.holds(self.inputs.states, lambda target: self.present(candidate.show, target))

    def run(self) -> Result:
        shown: dict[int, Shown] = {}
        # 1. fixed slots keep what they show, and what they show is taken
        if self.previous is not None:
            for slot in self.inputs.fixed:
                shown[slot] = self.previous.slots[slot]
                self.why[slot].append("held")
        # also a channel a fixed slot shows as a member of a pool: one channel has one slot
        taken = {s.channel for s in shown.values() if s.channel is not None}
        # 2. channels by rank: every free slot proposes its first candidate that holds
        position = {slot: self._next(slot, 0) for slot in SLOTS if slot not in shown}
        while True:
            proposals: dict[str, list[int]] = {}
            for slot, index in position.items():
                candidate = self.scene.stacks[slot][index]
                if candidate.show is not None and candidate.show not in self.scene.pools:
                    if candidate.show in taken:
                        self.why[slot].append(f"{candidate}: {candidate.show} is on a held slot")
                        position[slot] = self._next(slot, index + 1)
                        break
                    proposals.setdefault(candidate.show, []).append(slot)
            else:
                losers = self._contests(proposals, position)
                if not losers:
                    break
                for slot in losers:
                    position[slot] = self._next(slot, position[slot] + 1)
        for slot, index in position.items():
            candidate = self.scene.stacks[slot][index]
            if candidate.show is None:
                shown[slot] = Shown(index)
            elif candidate.show in self.scene.pools:
                shown[slot] = Shown(index, pool=candidate.show)
            else:
                shown[slot] = Shown(index, channel=candidate.show)
        # 3. pools
        waiting = self._pools(shown)
        for slot in SLOTS:
            self.why[slot].append(f"shows {shown[slot]}")
        return Result(dict(sorted(shown.items())), waiting, {slot: tuple(lines) for slot, lines in self.why.items()})

    def _next(self, slot: int, start: int) -> int:
        """The index of the first candidate from `start` on that holds (the stack ends in one that always does)."""
        stack = self.scene.stacks[slot]
        # the last one holds always and is never contested (a pool or "-": the model adds auto to other stacks)
        for index in range(start, len(stack) - 1):
            candidate = stack[index]
            if self.holds(candidate):
                return index
            assert candidate.when is not None
            explanation = candidate.when.explain(self.inputs.states, lambda t, c=candidate: self.present(c.show, t))
            self.why[slot].append(f"{candidate}: doesn't hold ({explanation})")
        return len(stack) - 1

    def _contests(self, proposals: Mapping[str, list[int]], position: Mapping[int, int]) -> list[int]:
        """The slots that lose a channel several slots propose: it goes to the highest rank, ties to the left."""
        losers: list[int] = []
        for channel, slots in proposals.items():
            if len(slots) < 2:
                continue
            winner = min(slots, key=lambda slot: (position[slot], slot))
            for slot in slots:
                if slot != winner:
                    rank, winner_rank = position[slot] + 1, position[winner] + 1
                    how = "tie, to the left" if rank == winner_rank else f"rank {winner_rank} there, {rank} here"
                    self.why[slot].append(f"{channel}: on slot {winner} ({how})")
                    losers.append(slot)
        return losers

    def _pools(self, shown: dict[int, Shown]) -> dict[str, tuple[str, ...]]:
        """Hands out the members of each pool to its slots; the members left over wait."""
        with_slot: set[str] = {s.channel for s in shown.values() if s.channel is not None}
        waiting: dict[str, tuple[str, ...]] = {}
        # pools of channels first: a slot meant for a channel gets it before `auto` takes it as a whole
        order = [pool for pool in self.scene.pools if pool not in (AUTO, PEOPLE)] + [PEOPLE, AUTO]
        for pool in order:
            if pool == AUTO and self.scene.pools[PEOPLE].share == AUTO and PEOPLE in waiting:
                # before auto hands out its members: the people that got no slot of their own take some of its slots
                left = self._share(shown, waiting.pop(PEOPLE), with_slot)
                if left:
                    waiting[PEOPLE] = left
            slots = sorted(slot for slot, s in shown.items() if s.pool == pool and slot not in self.inputs.fixed)
            held = {s.member for slot, s in shown.items() if s.pool == pool and slot in self.inputs.fixed}
            members = [member for member in self._members(pool, with_slot) if member not in held]
            if not slots:
                # applications and people wait for a slot; channels of a pool without one are just not shown
                if members and pool in (AUTO, PEOPLE):
                    waiting[pool] = tuple(members)
                continue
            assigned: dict[int, str] = {}
            if pool == AUTO:
                for slot, member in self.inputs.pins.items():
                    if member in with_slot:
                        # a channel pinned while it had no slot, and has one now: it shows there
                        self.why[slot].append(f"pin {member}: on another slot")
                    elif slot in slots:
                        assigned[slot] = member
                        if member not in members:
                            # a pin stays after its application stopped playing
                            members.append(member)
            if pool in (AUTO, PEOPLE) and self.previous is not None:
                for slot in slots:
                    before = self.previous.slots.get(slot)
                    if (
                        slot not in assigned
                        and before is not None
                        and before.pool == pool
                        and before.member in members
                        and before.member not in assigned.values()
                    ):
                        assigned[slot] = before.member
            free = [member for member in members if member not in assigned.values()]
            for slot in slots:
                if slot not in assigned and free:
                    assigned[slot] = free.pop(0)
            if free:
                waiting[pool] = tuple(free)
            for slot in slots:
                member = assigned.get(slot)
                channel = member if member in self.scene.channels else None
                shown[slot] = Shown(shown[slot].candidate, channel=channel, pool=pool, member=member)
                if channel is not None:
                    # a channel one pool gave a slot is not a member of the next one
                    with_slot.add(channel)
        return waiting

    def _share(self, shown: dict[int, Shown], people: tuple[str, ...], with_slot: set[str]) -> tuple[str, ...]:
        """
        Puts people on slots of `auto`: each keeps the slot it had, a new one takes the rightmost slot whose
        application doesn't keep it (the applications fill from the left), else the rightmost one left. Slots where
        `auto` is the first candidate go first: nothing above takes them over, so the person needn't move again
        (e.g. when the delay of `call` ends and its strips come). The people that find none wait.
        """
        slots = sorted(slot for slot, s in shown.items() if s.pool == AUTO and slot not in self.inputs.fixed)
        members = set(self._members(AUTO, with_slot))
        keeping: set[int] = set()
        assigned: dict[int, str] = {}
        for slot in slots:
            before = self.previous.slots.get(slot) if self.previous is not None else None
            if before is None:
                continue
            if before.pool == PEOPLE and before.member in people and before.member not in assigned.values():
                assigned[slot] = before.member
            elif (before.pool == AUTO and before.member in members) or slot in self.inputs.pins:
                keeping.add(slot)
        left: list[str] = []
        for person in people:
            if person in assigned.values():
                continue
            home = self.inputs.homes.get(person)
            if (
                home is not None
                and home in self.inputs.fixed
                and shown[home].pool == AUTO
                and shown[home].member is None
            ):
                # their slot is empty but dwells (they left a moment ago): wait for it rather than take another
                left.append(person)
                continue
            if home is not None and home in slots and home not in assigned and home not in keeping:
                assigned[home] = person
                continue
            free: list[int] = [slot for slot in slots if slot not in assigned]
            # free before an application's (moving one now is worse than maybe later), then stable; the rightmost
            ranked = sorted(free, key=lambda s: (s not in keeping, shown[s].candidate == 0, s))
            slot = ranked[-1] if ranked else None
            if slot is None:
                left.append(person)
                continue
            assigned[slot] = person
            if slot in keeping:
                self.why[slot].append(f"{shown[slot]}: gives way to {person}")
        for slot, person in assigned.items():
            shown[slot] = Shown(shown[slot].candidate, pool=PEOPLE, member=person)
            self.why[slot].append(f"auto: shared with people, {person}")
        return tuple(left)

    def _members(self, pool: str, with_slot: set[str]) -> list[str]:
        observation = self.inputs.observation
        if pool == PEOPLE:
            return list(people_without_channel(self.scene, observation))
        if pool == AUTO:
            members: dict[str, None] = {}
            for app in observation.playing:
                if excluded(self.scene, app):
                    continue
                owner = owner_of(self.scene, app)
                if owner is None:
                    members[app] = None
                elif owner not in with_slot:
                    # a channel without a slot goes in as a whole: one owner per stream
                    members[owner] = None
            return list(members)
        return [
            channel
            for channel in self.scene.members_of(self.scene.pools[pool].channels)
            if channel in self.inputs.present and channel not in with_slot
        ]
