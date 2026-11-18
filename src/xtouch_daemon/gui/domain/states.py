"""
The states and modes of a file as the page States shows them: modes first, where each is used, and what the daemon
says about it right now.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from xtouch_daemon.gui.domain.channels import stack_of
from xtouch_daemon.live.messages import Snapshot, StateView
from xtouch_daemon.slots.expressions import ExpressionError, parse

OVERRIDES = ("auto", "on", "off")


def ordered(states: Mapping[str, Any]) -> list[str]:
    """The names of the states, the modes first, each in the order of the file."""
    modes = [name for name, state in states.items() if isinstance(state, Mapping) and state.get("mode")]
    return modes + [name for name in states if name not in modes]


def _names(text: Any) -> frozenset[str]:
    if not isinstance(text, str) or not text.strip():
        return frozenset()
    try:
        return parse(text).states
    except ExpressionError:
        return frozenset()


def _condition(entry: Any) -> Any:
    if isinstance(entry, str):
        return entry.partition(" if ")[2]
    return entry.get("when") if isinstance(entry, Mapping) else None  # pyright: ignore[reportUnknownMemberType]


def state_uses(values: Mapping[str, Any], name: str) -> tuple[str, ...]:
    """Where a state or mode is asked about: `slot 2`, `controls 5`, `state call` (its `when`)."""
    found: list[str] = []
    for slot, stack in values.get("slots", {}).items():
        if any(name in _names(_condition(entry)) for entry in stack_of(stack)):
            found.append(f"slot {slot}")
    for slot, controls in values.get("controls", {}).items():
        if any(name in _names(_condition(entry)) for entry in stack_of_controls(controls)):
            found.append(f"controls {slot}")
    for other, state in values.get("state", {}).items():
        if isinstance(state, Mapping) and name in _names(state.get("when")):  # pyright: ignore[reportUnknownMemberType]
            found.append(f"state {other}")
    return tuple(found)


def stack_of_controls(value: Any) -> list[Any]:
    """The controls of a slot: one table, or a list of them."""
    return [value] if isinstance(value, Mapping) else list(value) if isinstance(value, list) else []


def live_state(snapshot: Snapshot | None, name: str) -> StateView | None:
    """What the daemon says about a state, None while it does not run this file's slots."""
    if snapshot is None or snapshot.slots is None:
        return None
    return next((state for state in snapshot.slots.states if state.name == name), None)


def describe_live(state: StateView | None) -> str:
    """`on since 21:04 (mumble runs), override on`, or why there is nothing to tell."""
    if state is None:
        return "No daemon runs these states right now."
    text = "on" if state.value else "off"
    if state.since is not None:
        text += f" since {datetime.fromisoformat(state.since).astimezone().strftime('%H:%M')}"
    if state.source:
        text += f" ({state.source})"
    if state.override != "auto":
        text += f", override {state.override}"
    return text
