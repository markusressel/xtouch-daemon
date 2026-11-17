"""
The distinct outcomes of a configuration: every combination of the modes, states and presence its stacks ask about
that changes what the slots show, as `check-config`, `simulate --table` and the GUI's grid show them.
"""

import itertools
from collections.abc import Iterable
from dataclasses import dataclass

from xtouch_daemon.slots.inputs import Attendee, Observation
from xtouch_daemon.slots.model import APPS, AUTO, BUILT_IN, DEFAULT, PEOPLE, Scene
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
    """The channels and pools of channels that are absent, the built-in pools that are present, see `simulate()`."""


PEOPLE_NAMES = ("Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi")
"""The people of a simulated call, in their order."""


def dimensions(scene: Scene) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    The states (modes excluded) and the channels and pools whose presence the stacks ask about, in their order, and
    `apps` and `people` where stacks name them (with members, they fill their slots). A composed state is no
    dimension of its own but follows from the states it names, so the table never has `call` together with `not
    call`.
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
    for pool in (APPS, PEOPLE):
        if any(candidate.show == pool for slot in SLOTS for candidate in scene.stacks[slot]):
            presence[pool] = None
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


def notes(scene: Scene) -> list[str]:
    """
    What `check-config` points out in a valid configuration: candidates that never show, and people that can sit
    nowhere.
    """
    result: list[str] = []
    for slot in SLOTS:
        stack = scene.stacks[slot]
        for above, candidate in itertools.pairwise(stack):
            if above.when is None and above.show in scene.pools and candidate.show in scene.channels:
                result.append(
                    f"slots.{slot}: {candidate} never shows: {above.show} always holds, and a slot it has no member "
                    "for goes to the pool or - right below it"
                )
                break
    shown = {candidate.show for stack in scene.stacks.values() for candidate in stack}
    asked = bool(scene.people.model_fields_set or scene.people.model_extra) or any(
        channel.type == "person" and channel.in_pool for channel in scene.channels.values()
    )
    if asked and not shown & {PEOPLE, AUTO}:
        result.append("people: no slot shows people or auto, so the people of the voice chat sit nowhere")
    return result


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


def simulate(
    scene: Scene, mode: str, on: Iterable[str], flipped: Iterable[str], people: int = 0, apps: int = 0
) -> Result:
    """
    What the slots show in the mode with the states `on` on: the channels and pools of channels are present, the
    built-in pools empty, except those `flipped` (absent; `auto`: an application plays; `apps` and `people`: as many
    as there are slots). `people` and `apps`: so many people in the call and applications that play.
    """
    flipped = set(flipped)
    values = states_for(scene, mode, on)
    gone = {channel for name in flipped if name not in BUILT_IN for channel in _channels_of(scene, name)}
    present = frozenset(name for name in scene.channels if name not in gone)
    apps = max(apps, len(SLOTS) if APPS in flipped else 1 if AUTO in flipped else 0)
    people = max(people, len(SLOTS) if PEOPLE in flipped else 0)
    names = (*PEOPLE_NAMES, *(f"Person {n}" for n in range(len(PEOPLE_NAMES) + 1, people + 1)))[:people]
    observation = Observation(
        playing=tuple(f"app {n}" for n in range(1, apps + 1)),
        voice_chat=people > 0,
        people=tuple(Attendee(name, name) for name in names),
    )
    return resolve(scene, Inputs(values, present, observation, order=names))


def _outcome(scene: Scene, mode: str, on: set[str], flipped: set[str]) -> tuple[str, ...]:
    result = simulate(scene, mode, on, flipped)
    return tuple(shown.pool or shown.channel or "-" for shown in result.slots.values())


def _label(scene: Scene, mode: str, on: tuple[str, ...], flipped: tuple[str, ...]) -> str:
    states = " and ".join(([] if mode == DEFAULT else [mode]) + list(on))
    changes = [f"{name} {_flipped(name)}" for name in flipped]
    return ", ".join(([states] if states else []) + changes) or DEFAULT


def _flipped(name: str) -> str:
    """What flipping a channel or pool means: absent, `auto` present, `apps` and `people` fill their slots."""
    return "present" if name == AUTO else "fill" if name in BUILT_IN else "absent"


def _channels_of(scene: Scene, name: str) -> tuple[str, ...]:
    """A channel, or the channels of a pool of channels."""
    return scene.channels_of(name) if name in scene.pools else (name,)


def _sourced(scene: Scene, names: Iterable[str]) -> list[str]:
    """The states `names` stand for: composed ones by the states they name, in turn."""
    result: dict[str, None] = {}
    for name in sorted(names):
        if name in scene.conditions:
            result.update((other, None) for other in _sourced(scene, scene.conditions[name].states))
        else:
            result[name] = None
    return list(result)
