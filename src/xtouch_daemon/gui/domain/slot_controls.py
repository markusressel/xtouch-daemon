"""
The controls of a slot (`[controls].<n>`) as the editor of the page Slots sees them: the entries of a slot (one table,
or a list of them, each with its `when`), the parts each sets, where each is in the file and its problems, and how a
part starts once it is added. Toolkit-free; `gui/quick/pages/slots_controls.py` shows it.
"""

import copy
from collections.abc import Mapping
from typing import Any

from xtouch_daemon.config.bindings import HOME_ASSISTANT
from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain.slots_document import OptionPath
from xtouch_daemon.gui.domain.states import stack_of_controls
from xtouch_daemon.slots.model import CONTROL_BUTTONS, CONTROL_PARTS

type Entry = dict[str, Any]
"""An entry of the controls of a slot: its parts, `when` and `id`, as in the file."""

PART_TITLES = {
    "fader": "Fader",
    "encoder": "Encoder",
    "select": "Select",
    "rec": "Rec",
    "solo": "Solo",
    "meter": "Meter",
    "color": "Color",
    "lcd": "LCD line",
}
"""The parts of a slot that `[controls]` can claim, by their names on the device (the LCD: its second line)."""

START: dict[str, Any] = {
    "fader": {},
    "encoder": {},
    "select": {},
    "rec": {},
    "solo": {},
    "meter": {},
    "color": "white",
    "lcd": {},
}
"""
What a part is once it is added: a color is white; the others are empty, and their problems at the fields say what
they still need (a program's `set` or `watch`, a button's `press` or `led`).
"""


def entries(values: Mapping[str, Any], slot: int) -> list[Entry]:
    """The entries of the controls of a slot, copies of the file's (tables only: another value is a problem)."""
    raw = stack_of_controls(values.get("controls", {}).get(str(slot)))
    return [copy.deepcopy(dict(entry)) for entry in raw if isinstance(entry, Mapping)]  # pyright: ignore[reportUnknownArgumentType]


def listed(values: Mapping[str, Any], slot: int) -> bool:
    """Whether the file has the controls of the slot as a list (`[[controls.3]]`), rather than one table."""
    return isinstance(values.get("controls", {}).get(str(slot)), list)


def controls_value(found: list[Entry]) -> Entry | list[Entry] | None:
    """The value of `[controls].<n>` for the entries: one table, a list of several, None for none."""
    if not found:
        return None
    return found[0] if len(found) == 1 else found


def entry_path(slot: int, index: int, as_list: bool) -> OptionPath:
    """Where an entry is in the file: `controls.3`, or `controls.3[1]` in a list."""
    return ("controls", str(slot), index) if as_list else ("controls", str(slot))


def parts(entry: Mapping[str, Any]) -> list[str]:
    """The parts the entry sets, in the order of the device (`CONTROL_PARTS`)."""
    return [name for name in CONTROL_PARTS if name in entry]


def missing(entry: Mapping[str, Any]) -> list[str]:
    """The parts the entry could set but does not."""
    return [name for name in CONTROL_PARTS if name not in entry]


def uses_home_assistant(entry: Mapping[str, Any]) -> bool:
    """Whether a part of the entry is in Home Assistant: its `id` names the entities there."""

    def bound(value: object) -> bool:
        return value == HOME_ASSISTANT

    for name in parts(entry):
        value = entry[name]
        if bound(value):
            return True
        if name in CONTROL_BUTTONS and isinstance(value, Mapping):
            table: Mapping[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
            if bound(table.get("press")) or bound(table.get("led")):
                return True
    return False


def entry_text(entry: Mapping[str, Any]) -> str:
    """What an entry claims for people, e.g. "Rec and Meter"."""
    names = [PART_TITLES[name] for name in parts(entry)]
    if not names:
        return "Nothing"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def moved(found: list[Entry], index: int, offset: int) -> list[Entry]:
    """The entries with the one at `index` moved by `offset` (-1: up), within the list."""
    target = max(0, min(len(found) - 1, index + offset))
    result = list(found)
    result.insert(target, result.pop(index))
    return result


def entry_problems(problems: list[Problem], path: OptionPath) -> list[Problem]:
    """The problems of the entry at `path` that no field of a part, of `when` or of `id` shows."""
    fields = {*CONTROL_PARTS, "when", "id"}
    return [
        problem
        for problem in problems
        if problem.path[: len(path)] == path and not set(problem.path[len(path) : len(path) + 1]) & fields
    ]


def custom_channels(values: Mapping[str, Any]) -> list[str]:
    """The `custom` channels of the file: a fader or an encoder of `[controls]` can set their values."""
    channels: Mapping[str, Any] = values.get("channel", {})
    return [
        name for name, channel in channels.items() if isinstance(channel, Mapping) and channel.get("type") == "custom"
    ]  # pyright: ignore[reportUnknownMemberType]


def modes_and_states(values: Mapping[str, Any]) -> list[str]:
    """The actions of a button that name the modes and states of the file: `cycle_modes`, `mode:<id>`, `toggle:<id>`."""
    states: Mapping[str, Any] = values.get("state", {})
    modes = [f"mode:{name}" for name, options in states.items() if isinstance(options, Mapping) and options.get("mode")]  # pyright: ignore[reportUnknownMemberType]
    return [*(["cycle_modes", *modes, "mode:default"] if modes else []), *(f"toggle:{name}" for name in states)]
