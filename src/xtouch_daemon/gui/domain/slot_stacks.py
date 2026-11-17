"""
The stacks of the slots as the page Slots edits them: the candidates of a slot (what it shows, its condition and
the options of the place), changed one at a time and written back in the form the stack had (a string, a list of
strings, tables where a candidate has options).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from xtouch_daemon.gui.domain.channels import stack_of
from xtouch_daemon.gui.domain.states import stack_of_controls
from xtouch_daemon.slots.model import APP_OPTIONS, AUTO, CONTROLS, LOOK_OPTIONS

EMPTY = "-"
ALWAYS = "always"


@dataclass(frozen=True)
class Row:
    """A candidate of a stack."""

    show: str
    """A channel, a pool (`auto`), or `-` for nothing."""
    when: str = ""
    """Its condition, "" for always."""
    options: Mapping[str, Any] = field(default_factory=dict[str, Any])
    """The options of the place."""

    @property
    def chips(self) -> tuple[str, ...]:
        """The condition in parts for people: `call or gaming` is one chip per `or`, `always` without one."""
        if not self.when.strip():
            return (ALWAYS,)
        return tuple(part.strip() for part in self.when.split(" or "))

    def entry(self) -> str | dict[str, Any]:
        """The candidate as the file has it: a string without options, else a table."""
        if not self.options:
            return f"{self.show} if {self.when.strip()}" if self.when.strip() else self.show
        table: dict[str, Any] = {"show": self.show}
        if self.when.strip():
            table["when"] = self.when.strip()
        return table | dict(self.options)


def row_of(entry: Any) -> Row:
    """A candidate of the file (a broken one shows what it can)."""
    if isinstance(entry, str):
        show, _, when = entry.partition(" if ")
        return Row(show.strip(), when.strip())
    if isinstance(entry, Mapping):
        options = {str(key): value for key, value in entry.items() if key not in ("show", "when")}  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        return Row(str(entry.get("show", "?")), str(entry.get("when") or ""), options)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return Row("?")


def rows(values: Mapping[str, Any], slot: int) -> list[Row]:
    """The candidates of a slot (1 for the leftmost one)."""
    return [row_of(entry) for entry in stack_of(values.get("slots", {}).get(str(slot)))]


def stack_value(stack: list[Row]) -> str | list[str | dict[str, Any]] | None:
    """What the file gets for a stack: one plain candidate is a string, None for none."""
    entries = [row.entry() for row in stack]
    if not entries:
        return None
    if len(entries) == 1 and isinstance(entries[0], str):
        return entries[0]
    return entries


def place_options(show: str) -> frozenset[str]:
    """The options a place takes for what it shows: its look, and for `auto` how it controls applications."""
    return LOOK_OPTIONS | (APP_OPTIONS if show == AUTO else frozenset())


def choices(values: Mapping[str, Any]) -> list[str]:
    """What a candidate can show: the channels, the pools (`auto` too), and `-`."""
    channels = list(values.get("channel", {}))
    pools = [name for name in values.get("pool", {}) if name != AUTO]
    return [*channels, AUTO, *pools, EMPTY]


def controls_text(values: Mapping[str, Any], slot: int) -> list[str]:
    """The controls of a slot for people: `select: toggle:call (when not call)`."""
    lines: list[str] = []
    for table in stack_of_controls(values.get("controls", {}).get(str(slot))):
        if not isinstance(table, Mapping):
            continue
        parts = [f"{name}: {_action(table[name])}" for name in CONTROLS if name in table]  # pyright: ignore[reportUnknownArgumentType]
        when = table.get("when")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        lines.append(", ".join(parts) + (f" (when {when})" if when else ""))
    return lines


def _action(value: Any) -> str:
    if isinstance(value, Mapping):
        return "launch " + " ".join(str(part) for part in value.get("launch", ()))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportUnknownVariableType]
    return str(value)
