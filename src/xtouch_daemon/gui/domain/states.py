"""
The states and modes of a file as the page States shows them: modes first, where each is used, and what the daemon
says about it right now.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
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


HOURS = 24
"""The hours of the history of a state (see `hours_on`): a day."""


@dataclass(frozen=True)
class Hour:
    """An hour of the clock in the history of a state."""

    start: datetime
    end: datetime
    """Its end: an hour later, or now for the current hour."""
    on: float
    """Seconds the state was on in it."""
    known: float
    """Seconds of it the daemon watched the state: the share on is `on / known`; 0 for none."""

    @property
    def share(self) -> float | None:
        """How much of the hour the state was on (0..1), None for an hour the daemon didn't watch it."""
        return self.on / self.known if self.known else None

    def describe(self) -> str:
        """E.g. `14:00-15:00: on for 35 min`, and how long the daemon watched it if not all of it."""
        span = f"{self.start:%H:%M}-{self.end:%H:%M}"
        if not self.known:
            return f"{span}: no daemon watched it"
        if not self.on:
            text = "off"
        elif self.on >= self.known:
            text = "on"
        else:
            minutes = round(self.on / 60)
            text = f"on for {minutes} min" if minutes else "on for a moment"
        if self.known < (self.end - self.start).total_seconds() - 1:
            text += f", watched for {round(self.known / 60)} min"
        return f"{span}: {text}"


def hours_on(history: Sequence[tuple[float, bool]], now: float, hours: int = HOURS) -> tuple[Hour, ...]:
    """
    The last `hours` hours of the clock, the current one up to `now` (Unix times), oldest first: how long a state was
    on in each, from its changes (`StateView.history`). Before its first change the daemon didn't watch it.
    """
    current = datetime.fromtimestamp(now).astimezone().replace(minute=0, second=0, microsecond=0)
    result: list[Hour] = []
    for back in range(hours - 1, -1, -1):
        start = current - timedelta(hours=back)
        begin, end = start.timestamp(), min(start.timestamp() + 3600, now)
        on = known = 0.0
        for index, (moment, value) in enumerate(history):
            until = history[index + 1][0] if index + 1 < len(history) else now
            overlap = max(0.0, min(until, end) - max(moment, begin))
            known += overlap
            on += overlap if value else 0.0
        result.append(Hour(start, datetime.fromtimestamp(end).astimezone(), on, known))
    return tuple(result)
