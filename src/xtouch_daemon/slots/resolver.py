"""
What each of the 8 slots shows: fixed slots first, then the channels by rank, then the pools. Pure: the same inputs
give the same result; only the applications look at the previous one, to keep their slots.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from xtouch_daemon.hardware import protocol
from xtouch_daemon.slots.inputs import (
    App,
    Channel,
    Device,
    Member,
    Observation,
    Person,
    channel_of,
    devices_of,
    excluded,
    owner_of,
    people_of,
    pool_of_app,
    pool_people,
    pool_present,
)
from xtouch_daemon.slots.model import APPS, AUTO, DEVICES, PEOPLE, Candidate, PoolConfig, Scene

SLOTS = range(1, protocol.STRIPS + 1)
KINDS: Mapping[str, tuple[str, ...]] = {
    APPS: (APPS,),
    PEOPLE: (PEOPLE,),
    DEVICES: (DEVICES,),
    AUTO: (PEOPLE, APPS),
}
"""The members each built-in pool hands out: `auto` the people and the applications, the people first."""


@dataclass(frozen=True)
class Shown:
    """What a slot shows: a channel, a member of a pool (an application, a person or a channel), or nothing."""

    candidate: int | None
    """The index of the candidate in the slot's stack; None for nothing at all."""
    channel: str | None = None
    """The channel it shows: of a channel candidate, or a channel that is a member of a pool."""
    pool: str | None = None
    member: Member | None = None
    """
    The application, channel or person a pool hands out (`pool` is `people` for a person, also on a slot of
    `auto`), None for an empty pool (a dark slot).
    """

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
    pins: Mapping[int, App | Channel] = field(default_factory=dict[int, App | Channel])
    """The members pinned to slots of `apps` and `auto` with the `pick` encoder."""
    order: tuple[str, ...] = ()
    """The order of the people (see `_people()`)."""


@dataclass(frozen=True)
class Result:
    slots: Mapping[int, Shown]
    waiting: Mapping[str, tuple[Member, ...]]
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
            dark = shown[slot].pool is not None and shown[slot].member is None
            self.why[slot].append(
                f"shows nothing: {shown[slot].pool} has none left" if dark else f"shows {shown[slot]}"
            )
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

    def _pools(self, shown: dict[int, Shown]) -> dict[str, tuple[Member, ...]]:
        """
        Hands out the members of the pools to their slots (see `_chain()`): the pools of channels first, then
        `apps`, `people` and `auto` contest the rest (`_contest()`). The members left over wait.
        """
        fixed = self.inputs.fixed
        with_slot: set[str] = {s.channel for s in shown.values() if s.channel is not None}
        # what a held slot shows is not handed out again
        held = {s.member for slot, s in shown.items() if slot in fixed and s.member is not None}
        chains = {
            slot: self._chain(slot, s.candidate)
            for slot, s in shown.items()
            if slot not in fixed and s.pool is not None and s.candidate is not None
        }
        open_slots = self._of_channels(shown, chains, with_slot, held)
        return self._contest(shown, open_slots, with_slot, held)

    def _chain(self, slot: int, index: int) -> list[int]:
        """
        The pool candidate at `index` and the candidates below it that hold while they are pools, up to and with a
        `-`: a pool hands a slot it has no member for down to the next of them. A channel ends the chain.
        """
        stack = self.scene.stacks[slot]
        chain = [index]
        for below in range(index + 1, len(stack)):
            candidate = stack[below]
            if candidate.show is not None and candidate.show not in self.scene.pools:
                break
            if self.holds(candidate):
                chain.append(below)
                if candidate.show is None:
                    break
        return chain

    def _fill_order(self, pool: str, slots: Iterable[int], index: Mapping[int, int]) -> list[int]:
        """
        The slots in the order a pool fills them: from its side. The people first take the slots where they are the
        first candidate (`index` is theirs on each slot): nothing above can take those over. They sit in their order
        and keep no slot, so a slot a candidate above takes back would move every one of them.
        """
        right = self.scene.side(pool) == "right"
        first = pool == PEOPLE or pool in self.scene.people_pools
        return sorted(slots, key=lambda slot: (first and index[slot] != 0, -slot if right else slot))

    def _of_channels(
        self, shown: dict[int, Shown], chains: Mapping[int, list[int]], with_slot: set[str], held: set[Member]
    ) -> dict[int, list[int]]:
        """
        The pools of channels, by their order (they come before the built-in pools in a chain, see the model): a
        slot whose pool has no channel left goes on down its chain. The slots left, with the rest of their chains.
        """
        stacks = self.scene.stacks
        rest = {slot: list(chain) for slot, chain in chains.items()}
        while True:
            heads = {slot: stacks[slot][chain[0]].show for slot, chain in rest.items()}
            pools = [
                pool
                for pool, config in self.scene.pools.items()
                if isinstance(config, PoolConfig) and pool in heads.values()
            ]
            if not pools:
                return rest
            for pool in pools:
                index = {slot: rest[slot][0] for slot, head in heads.items() if head == pool}
                members = [
                    Channel(channel)
                    for channel in self.scene.channels_of(pool)
                    if channel in self.inputs.present and channel not in with_slot and Channel(channel) not in held
                ]
                for slot in self._fill_order(pool, index, index):
                    if members:
                        member = members.pop(0)
                        shown[slot] = Shown(index[slot], channel=member.id, pool=pool, member=member)
                        # a channel one pool gave a slot is not a member of the next one
                        with_slot.add(member.id)
                        del rest[slot]
                    elif len(rest[slot]) > 1:
                        self.why[slot].append(f"{pool}: none left for this slot")
                        rest[slot].pop(0)
                    else:
                        # channels of a pool without a slot are just not shown: the slot is dark
                        self.why[slot].append(f"{pool}: none left for this slot")
                        shown[slot] = Shown(index[slot], pool=pool)
                        del rest[slot]

    def _contest(
        self, shown: dict[int, Shown], rest: Mapping[int, list[int]], with_slot: set[str], held: set[Member]
    ) -> dict[str, tuple[Member, ...]]:
        """
        `apps`, `people` and `auto` (people before applications) hand out their members. The people fill their slots
        in their order, the applications keep the slot they had; each from its side (`_fill_order()`). A slot that
        both fill goes to the one higher in its stack: the other gives that slot up and hands out again.
        """
        stacks = self.scene.stacks
        # per slot the kinds of members it takes, in its order, with the candidate that takes them
        kinds: dict[int, dict[str, int]] = {}
        ends: dict[int, int] = {}
        for slot, chain in rest.items():
            kinds[slot] = {}
            for index in chain:
                show = stacks[slot][index].show
                if show is None:
                    break
                for kind in KINDS.get(show, (show,)):
                    kinds[slot].setdefault(kind, index)
            # without a member: dark, as the last pool of its chain, or `-`
            ends[slot] = chain[-1]
        people = [person for person in self._people(with_slot) if person not in held]
        apps = [member for member in self._apps(with_slot) if member not in held]
        pinned: dict[int, Member] = {}
        for slot, member in self.inputs.pins.items():
            if channel_of(member) in with_slot or member in held:
                # a channel pinned while it had no slot, and has one now, or a member a held slot shows: it shows
                # there (the pin takes effect once that slot is let go)
                self.why[slot].append(f"pin {member}: on another slot")
            elif APPS in kinds.get(slot, {}):
                pinned[slot] = member
                if member not in apps:
                    # a pin stays after its application (or channel) stopped playing
                    apps.append(member)
        devices = [device for device in devices_of(self.scene, self.inputs.observation) if device not in held]
        members: dict[str, list[Member]] = {PEOPLE: list(people), APPS: apps, DEVICES: list(devices)}
        # the pools of your own come before the built-in ones: the people, then the applications
        for pool in self.scene.people_pools:
            members[pool] = list(pool_people(self.scene, pool, self.inputs.observation, with_slot))
        for pool in self.scene.apps_pools:
            members[pool] = self._pool_apps(pool, with_slot)
        for pool in (*self.scene.people_pools, *self.scene.apps_pools):
            members[pool] = [member for member in members[pool] if member not in held]
        sources = (*self.scene.people_pools, PEOPLE, *self.scene.apps_pools, APPS, DEVICES)
        order = {
            kind: self._fill_order(
                kind,
                (slot for slot in kinds if kind in kinds[slot] and slot not in pinned),
                {slot: kinds[slot][kind] for slot in kinds if kind in kinds[slot]},
            )
            for kind in sources
        }
        lost: dict[str, set[int]] = {kind: set() for kind in sources}
        while True:
            taken: dict[str, dict[int, Member]] = {}
            for kind in sources:
                free = [slot for slot in order[kind] if slot not in lost[kind]]
                if kind == PEOPLE or kind in self.scene.people_pools:
                    taken[kind] = dict(zip(free, members[kind], strict=False))
                elif kind == APPS:
                    taken[kind] = self._place(apps, pinned, free, (APPS, AUTO))
                else:
                    taken[kind] = self._place(members[kind], {}, free, (kind,))
            contested = {slot for slot in kinds if sum(slot in taken[kind] for kind in sources) > 1}
            if not contested:
                break
            for slot in contested:
                # it ends: a kind only ever loses slots, and a slot one won stays taken
                takers = [kind for kind in sources if slot in taken[kind]]
                first = min(takers, key=lambda kind: (kinds[slot][kind], sources.index(kind)))
                for kind in takers:
                    if kind != first:
                        lost[kind].add(slot)
        for slot in kinds:
            source = next((kind for kind in sources if slot in taken[kind]), None)
            member: Member | None = taken[source][slot] if source is not None else None
            if member is None or source is None:
                # every pool of the chain came away empty: each says so, the slot is dark
                for index in rest[slot]:
                    if (show := stacks[slot][index].show) is not None:
                        self.why[slot].append(f"{show}: none left for this slot")
                end = ends[slot]
                show = stacks[slot][end].show
                shown[slot] = Shown(end) if show is None else Shown(end, pool=show)
                continue
            index = kinds[slot][source]
            for above in sorted({kinds[slot][other] for other in kinds[slot]} - {index}):
                if above < index:
                    self.why[slot].append(f"{stacks[slot][above].show}: none left for this slot")
            before = self.previous.slots.get(slot) if self.previous is not None else None
            if isinstance(member, Person):
                if before is not None and before.member is not None and not isinstance(before.member, Person):
                    self.why[slot].append(f"{before}: gives way to {member}")
                shown[slot] = Shown(index, channel=member.channel, pool=source, member=member)
            elif isinstance(member, Device):
                shown[slot] = Shown(index, pool=DEVICES, member=member)
            else:
                shown[slot] = Shown(index, channel=channel_of(member), pool=stacks[slot][index].show, member=member)
        waiting: dict[str, tuple[Member, ...]] = {}
        for kind in sources:
            if left := tuple(member for member in members[kind] if member not in taken[kind].values()):
                waiting[kind] = left
        return waiting

    def _place(
        self, apps: list[Member], pinned: Mapping[int, Member], slots: list[int], pools: tuple[str, ...]
    ) -> dict[int, Member]:
        """
        The applications (or devices) on their slots: pinned ones, then each on the slot it had in one of `pools`,
        then the others in order.
        """
        placed = dict(pinned)
        if self.previous is not None:
            for slot in slots:
                before = self.previous.slots.get(slot)
                if (
                    before is not None
                    and before.pool in pools
                    and before.member in apps
                    and before.member not in placed.values()
                ):
                    placed[slot] = before.member
        free = [member for member in apps if member not in placed.values()]
        for slot in slots:
            if slot not in placed and free:
                placed[slot] = free.pop(0)
        return placed

    def _pool_apps(self, pool: str, with_slot: set[str]) -> list[Member]:
        """The members of a pool of applications of your own, but not those of an `apps` channel with a slot."""
        members: dict[Member, None] = {}
        for app in self.inputs.observation.pool_playing.get(pool, ()):
            if pool_of_app(self.scene, app) != pool:
                continue
            owner = owner_of(self.scene, app)
            if owner is None or owner not in with_slot:
                members[App(app)] = None
        return list(members)

    def _people(self, with_slot: set[str]) -> list[Person]:
        """
        The members of `people` in their order (`Inputs.order`: the configured one, then who was seen first; others
        after them). A `person` channel goes by its id and its names, the others by name.
        """
        people = people_of(self.scene, self.inputs.observation, self.inputs.present, with_slot)
        rank = {name.lower(): index for index, name in enumerate(self.inputs.order)}

        def rank_of(person: Person) -> int:
            names = (
                (person.name,)
                if person.channel is None
                else (person.channel, *self.scene.channels[person.channel].people)
            )
            return min((rank[name.lower()] for name in names if name.lower() in rank), default=len(rank))

        return sorted(people, key=lambda person: (rank_of(person), people.index(person)))

    def _apps(self, with_slot: set[str]) -> list[Member]:
        """The members of `apps`, in the order they started: applications, and `apps` channels as a whole."""
        members: dict[Member, None] = {}
        for app in self.inputs.observation.playing:
            if excluded(self.scene, app):
                continue
            owner = owner_of(self.scene, app)
            if owner is None:
                members[App(app)] = None
            elif owner not in with_slot:
                # a channel without a slot goes in as a whole: one owner per stream
                members[Channel(owner)] = None
        return list(members)
