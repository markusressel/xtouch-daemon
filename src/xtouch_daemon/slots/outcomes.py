"""
The distinct outcomes of a configuration: every combination of the modes, states and presence its stacks ask about
that changes what the slots show, as `check-config`, `simulate --table` and the GUI's grid show them.
"""

import itertools
from collections.abc import Iterable
from dataclasses import dataclass

from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.model import AUTO, DEFAULT, Scene
from xtouch_daemon.slots.resolver import SLOTS, Inputs, Result, resolve
from xtouch_daemon.slots.states import composed_order


@dataclass(frozen=True)
class Outcome:
    label: str
    """The combination, e.g. `gaming and call, people present`."""
    slots: tuple[str, ...]
    """What each slot shows: a channel, a pool, or `-`."""
    mode: str = DEFAULT
    on: tuple[str, ...] = ()
    """The states that are on."""
    flipped: tuple[str, ...] = ()
    """The channels and pools that are absent (`auto`: present), see `simulate()`."""


def dimensions(scene: Scene) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    The states (modes excluded) and the channels and pools whose presence the stacks ask about, in their order. A
    composed state is no dimension of its own but follows from the states it names, so the table never has `call`
    together with `not call`.
    """
    states: dict[str, None] = {}
    presence: dict[str, None] = {}
    for slot in SLOTS:
        for candidate in scene.stacks[slot]:
            if candidate.when is None:
                continue
            states.update((name, None) for name in _sourced(scene, candidate.when.states) if name in scene.states)
            for target in sorted(candidate.when.presence, key=lambda target: target or ""):
                name = target if target is not None else candidate.show
                assert name is not None, "the model has no present on - (nothing)"
                presence[name] = None
    return tuple(name for name in states if not scene.states[name].mode), tuple(presence)


def outcomes(scene: Scene) -> list[Outcome]:
    """One row per combination that shows something no simpler combination shows."""
    states, presence = dimensions(scene)
    asked = {
        name
        for slot in SLOTS
        for c in scene.stacks[slot]
        if c.when is not None
        for name in _sourced(scene, c.when.states)
    }
    modes = [DEFAULT, *(mode for mode in scene.modes if mode in asked)]
    combinations = [
        (mode, on, flipped)
        for mode in modes
        for count in range(len(states) + len(presence) + 1)
        for on_count in range(min(count, len(states)) + 1)
        for on in itertools.combinations(states, on_count)
        for flipped in itertools.combinations(presence, count - on_count)
    ]
    # the simplest first: fewer states and presence changes, the default mode before others
    combinations.sort(key=lambda c: (len(c[1]) + len(c[2]) + (c[0] != DEFAULT), len(c[2]), modes.index(c[0])))
    rows: list[Outcome] = []
    seen: set[tuple[str, ...]] = set()
    for mode, on, flipped in combinations:
        slots = _outcome(scene, mode, set(on), set(flipped))
        if slots not in seen:
            seen.add(slots)
            rows.append(Outcome(_label(scene, mode, on, flipped), slots, mode, on, flipped))
    return rows


def table(rows: list[Outcome]) -> str:
    """The rows as text, with neighboring slots that always show the same merged (`3-6`)."""
    groups: list[list[int]] = []
    for index in range(len(SLOTS)):
        if groups and all(row.slots[index] == row.slots[groups[-1][0]] for row in rows):
            groups[-1].append(index)
        else:
            groups.append([index])
    heads = [str(g[0] + 1) if len(g) == 1 else f"{g[0] + 1}-{g[-1] + 1}" for g in groups]
    cells = [[row.label, *(row.slots[g[0]] for g in groups)] for row in rows]
    widths = [max(len(text) for text in column) for column in zip(["when", *heads], *cells, strict=True)]
    lines = [["when", *heads], *cells]
    return "\n".join(
        "  ".join(text.ljust(width) for text, width in zip(line, widths, strict=True)).rstrip() for line in lines
    )


def states_for(scene: Scene, mode: str, on: Iterable[str]) -> dict[str, bool]:
    """
    The value of every state and mode with `mode` and the states `on` on, the others off, and the composed ones
    that aren't in `on` from those (a composed state may name another one after it, so they go in their order).
    """
    on = set(on)
    values = {name: name in on for name in scene.states}
    values.update({name: name == mode for name in scene.modes})
    values[DEFAULT] = mode == DEFAULT
    for name in composed_order(scene):
        if name not in on:
            values[name] = scene.conditions[name].holds(values, lambda target: False)
    return values


def simulate(scene: Scene, mode: str, on: Iterable[str], flipped: Iterable[str]) -> Result:
    """
    What the slots show in the mode with the states `on` on: the channels and pools of channels are present, `auto`
    empty, except those `flipped` (absent; `auto`: an application plays).
    """
    flipped = set(flipped)
    values = states_for(scene, mode, on)
    gone = {channel for name in flipped if name != AUTO for channel in _channels_of(scene, name)}
    present = frozenset(name for name in scene.channels if name not in gone)
    observation = Observation(playing=("an application",) if AUTO in flipped else ())
    return resolve(scene, Inputs(values, present, observation))


def _outcome(scene: Scene, mode: str, on: set[str], flipped: set[str]) -> tuple[str, ...]:
    result = simulate(scene, mode, on, flipped)
    return tuple(shown.pool or shown.channel or "-" for shown in result.slots.values())


def _label(scene: Scene, mode: str, on: tuple[str, ...], flipped: tuple[str, ...]) -> str:
    states = " and ".join(([] if mode == DEFAULT else [mode]) + list(on))
    changes = [f"{name} {'present' if name == AUTO else 'absent'}" for name in flipped]
    return ", ".join(([states] if states else []) + changes) or DEFAULT


def _channels_of(scene: Scene, name: str) -> tuple[str, ...]:
    """A channel, or the channels of a pool of channels."""
    return scene.members_of(scene.pools[name].channels) if name in scene.pools else (name,)


def _sourced(scene: Scene, names: Iterable[str]) -> list[str]:
    """The states `names` stand for: composed ones by the states they name, in turn."""
    result: dict[str, None] = {}
    for name in sorted(names):
        if name in scene.conditions:
            result.update((other, None) for other in _sourced(scene, scene.conditions[name].states))
        else:
            result[name] = None
    return list(result)
