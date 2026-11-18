"""
The stacks of the slots as the page Slots edits them: the candidates of a slot (what it shows, its condition and
the options of the place), changed one at a time and written back in the form the stack had (a string, a list of
strings, tables where a candidate has options).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.channels import stack_of
from xtouch_daemon.gui.domain.states import stack_of_controls
from xtouch_daemon.live.messages import SlotsState, SlotView
from xtouch_daemon.slots import model
from xtouch_daemon.slots.expressions import ExpressionError, parse
from xtouch_daemon.slots.model import APPS, AUTO, BUILT_IN, CONTROLS, DEVICES, PEOPLE

EMPTY = "-"
ALWAYS = "always"


@dataclass(frozen=True)
class Row:
    """A candidate of a stack."""

    show: str
    """A channel, a pool (`auto`, `apps`, `people`, ...), or `-` for nothing."""
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


def readable(part: str, show: str, values: Mapping[str, Any]) -> tuple[str, bool]:
    """
    A chip of a condition in words, and whether it asks only about presence (no state or mode). `present` says what
    it means for the channel or pool it asks about: `browser plays`, `headset is connected`, `mum is in the voice
    chat`, `someone is in the voice chat`; `not present(game)` is `game doesn't play`.
    """

    def words(match: re.Match[str]) -> str:
        return presence_words(values, match.group("target") or show, bool(match.group("negated")))

    # in one pass: the words put in may contain "present" themselves
    text = _PRESENT.sub(words, part)
    try:
        presence_only = not parse(part).states
    except ExpressionError:
        presence_only = False
    return text, presence_only


_PRESENT = re.compile(r"\b(?P<negated>not\s+)?present\b(?:\s*\(\s*(?P<target>[a-z0-9_]+)\s*\))?")
"""`present` or `present(<target>)`, with a `not` before it."""


def presence_words(values: Mapping[str, Any], name: str, negated: bool = False) -> str:
    """What `present` (or `not present`) of a channel or pool means, in words: `browser plays`, `nobody is in ...`."""
    if name == APPS:
        return "no application plays" if negated else "an application plays"
    if name == PEOPLE:
        return "nobody is in the voice chat" if negated else "someone is in the voice chat"
    if name == DEVICES:
        return "no other device is connected" if negated else "another device is connected"
    if name == AUTO:
        return (
            "nothing plays and nobody is in the voice chat"
            if negated
            else "something plays or someone is in the voice chat"
        )
    if name in values.get("pool", {}):
        return f"no channel of {name} is there" if negated else f"a channel of {name} is there"
    channel = values.get("channel", {}).get(name)
    kind = channel.get("type") if isinstance(channel, Mapping) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    match kind:
        case "apps":
            return f"{name} doesn't play" if negated else f"{name} plays"
        case "output" | "input":
            return f"{name} is not connected" if negated else f"{name} is connected"
        case "person":
            return f"{name} is not in the voice chat" if negated else f"{name} is in the voice chat"
        case _:
            return f"{name} is absent" if negated else f"{name} is present"


def reasons(
    candidates: list[Row], shown: int | None, why: tuple[str, ...], values: Mapping[str, Any]
) -> dict[int, str]:
    """
    Why each candidate above the one shown did not win, from the why lines of the slot (see `slots.why`), in the
    words of the cards: `gaming is off, browser doesn't play`, `browser is on slot 3`, `none left for this slot`.
    """
    found: dict[int, str] = {}
    if shown is None:
        return found
    for index, row in enumerate(candidates[:shown]):
        keys = [f"{row.show} if {row.when.strip()}" if row.when.strip() else row.show, row.show]
        for key in keys:
            line = next((line for line in why if line.startswith(f"{key}: ")), None)
            if line is not None:
                found[index] = _reason(line.removeprefix(f"{key}: "), row.show, values)
                break
    return found


def _reason(text: str, show: str, values: Mapping[str, Any]) -> str:
    """A why line of a candidate in words: `doesn't hold (gaming is off, present: no)` is `gaming is off, ...`."""
    if text.startswith("on slot "):
        return f"{show} is {text}"
    if text == "none left for this slot" and is_pool(values, show):
        return f"no {free_words(values, show)}"
    if not (text.startswith("doesn't hold (") and text.endswith(")")):
        return text
    parts: list[str] = []
    for part in text.removeprefix("doesn't hold (").removesuffix(")").split(", "):
        match = _EXPLAINED.fullmatch(part)
        if match is None:
            parts.append(part)
        else:
            parts.append(presence_words(values, match.group("target") or show, match.group("value") == "no"))
    return ", ".join(parts)


_EXPLAINED = re.compile(r"present(?:\((?P<target>[a-z0-9_]+)\))?: (?P<value>yes|no)")
"""A part of `Condition.explain()` about presence: `present: no`, `present(game): yes`."""


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
    """The options a place takes for what it shows: its look, and for `apps` and `auto` how it acts on applications."""
    return model.place_options(show)


def is_pool(values: Mapping[str, Any], show: str) -> bool:
    """Whether a candidate shows a pool: a built-in one or one of `[pool.*]`."""
    return show in BUILT_IN or show in values.get("pool", {})


def member_text(member: str, devices: Mapping[str, str]) -> str:
    """
    A member a pool hands out, as the card names it: `app:firefox` is `firefox`, `person:Alice` `Alice`,
    `device:<node name>` the description of the device (`devices`: node name to description), a channel its id.
    """
    kind, _, name = member.partition(":")
    if not name:
        return member
    if kind == "device":
        return devices.get(name, name)
    return name


def member_summary(view: SlotView | None, audio: AudioState, slots: SlotsState | None) -> tuple[str, str] | None:
    """
    What the pool of the candidate shown hands out on the slot of `view`, in words, and who else of its kind waits
    for a slot (`Waiting: mpv, Spotify.`); None for a channel, a dark slot or while nothing tells. `slots` are the
    slots shown, for who waits.
    """
    if view is None or view.pool is None or view.member is None:
        return None
    devices = {device.name: device.description for device in (*audio.outputs, *audio.inputs)}
    kind = view.member.partition(":")[0]
    pool = {"app": APPS, "person": PEOPLE, "device": DEVICES}.get(kind, view.pool)
    waiting = slots.waiting.get(pool, ()) if slots is not None else ()
    names = ", ".join(member_text(other, devices) for other in waiting)
    return member_text(view.member, devices), f"Waiting: {names}." if names else ""


type RowState = Literal["", "shown", "passed", "unreached"]
"""Where a candidate is against the one the device shows: it, above it (did not win), below it (not reached); "" while
nothing tells."""


def row_state(index: int, shown: int | None, dark: bool) -> RowState:
    """
    Where the candidate `index` is against the one shown (`shown`, None while nothing tells); `dark`: none of them has
    anything to show, so all of them were passed.
    """
    if dark or (shown is not None and index < shown):
        return "passed"
    if shown is None:
        return ""
    return "shown" if index == shown else "unreached"


def pool_strip(show: str) -> str | None:
    """
    The strip type of what the pool `show` hands out: applications, people, outputs, or the channels of a pool of
    channels; None for `-`, which shows nothing.
    """
    if show == EMPTY:
        return None
    return {APPS: "auto", AUTO: "auto", PEOPLE: "voip", DEVICES: "output"}.get(show, "apps")


def free_words(values: Mapping[str, Any], name: str) -> str:
    """
    The condition a pool without one has, as a chip: a member that no slot has yet, e.g. `app without a slot` (not
    that the slot is free). `free_text` says it in full.
    """
    if name == APPS:
        return "app without a slot"
    if name == PEOPLE:
        return "person without a slot"
    if name == DEVICES:
        return "device without a slot"
    if name == AUTO:
        return "app or person without a slot"
    return f"{name} channel without a slot"


def free_text(values: Mapping[str, Any], name: str) -> str:
    """
    What a pool without a condition needs to fill a slot, for the tooltip of `free_words`: a member that no slot has
    yet (it may have members, all on other slots).
    """
    if name == APPS:
        return "An application that plays and has no slot yet"
    if name == PEOPLE:
        return "Someone in the voice chat who has no slot yet"
    if name == DEVICES:
        return "A device no channel has that has no slot yet"
    if name == AUTO:
        return "An application that plays, or someone in the voice chat, that has no slot yet"
    return f"A channel of {name} that is there and has no slot yet"


DEFAULT_COLOR = "white"
"""The color of a strip that doesn't set one."""


def lcd_colors(values: Mapping[str, Any], row: Row) -> tuple[tuple[str, str], ...]:
    """
    The colors the LCD of the slot has while `row` fills it, each with where it comes from: the candidate's own
    `color`, else the channel's or the pool's (`auto` has those of `[pool.auto]` and `[pool.people]`, a pool of
    channels those of its channels), else white. `-` is a dark LCD.
    """
    if row.show == EMPTY:
        return (("off", "nothing: the LCD is dark"),)
    own = row.options.get("color")
    if isinstance(own, str):
        return ((own, "color of this candidate"),)
    pools: Mapping[str, Any] = values.get("pool", {})
    channels: Mapping[str, Any] = values.get("channel", {})

    def of(section: Mapping[str, Any], name: str, where: str) -> tuple[str, str]:
        table = section.get(name)
        color = table.get("color") if isinstance(table, Mapping) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(color, str):
            return color, where
        return DEFAULT_COLOR, f"{where}: not set, white"

    if row.show == AUTO:
        return of(pools, AUTO, "applications: [pool.auto]"), of(pools, PEOPLE, "people: [pool.people]")
    if row.show in BUILT_IN:
        return (of(pools, row.show, f"[pool.{row.show}]"),)
    if row.show in channels:
        return (of(channels, row.show, f"[channel.{row.show}]"),)
    pool = pools.get(row.show)
    if isinstance(pool, Mapping):
        found: dict[str, list[str]] = {}
        for entry in pool.get("channels", ()):  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            for name, channel in channels.items():
                tags = channel.get("tags", ()) if isinstance(channel, Mapping) else ()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                if name == entry or entry in tags:
                    color, _ = of(channels, name, "")
                    found.setdefault(color, []).append(name)
        return tuple((color, "[channel.*] of " + ", ".join(names)) for color, names in found.items())
    return ()


def pool_text(values: Mapping[str, Any], name: str) -> str:
    """What a pool hands out, for the inspector: `Pool people: the people of the voice chat ..., from the right.`"""
    pools = values.get("pool", {})

    def side(pool: str, default: str) -> str:
        return str(pools.get(pool, {}).get("from", default))

    if name == APPS:
        what = f"the applications that play and have no slot, from the {side(APPS, 'left')}"
    elif name == PEOPLE:
        what = (
            "the people of the voice chat without a slot of their own, in their order, "
            f"from the {side(PEOPLE, 'right')}"
        )
    elif name == DEVICES:
        what = f"the outputs and inputs that no channel has, from the {side(DEVICES, 'left')}"
    elif name == AUTO:
        what = (
            f"the people (from the {side(PEOPLE, 'right')}) and the applications (from the {side(APPS, 'left')}), "
            "the people first"
        )
    else:
        what = f"the next present channel of its list, from the {side(name, 'left')}"
    return f"Pool {name}: {what}. With none left for a slot, the candidate below it gets the slot (a pool or `-`)."


def choices(values: Mapping[str, Any]) -> list[str]:
    """What a candidate can show: the channels, the pools (the built-in ones too), and `-`."""
    channels = list(values.get("channel", {}))
    pools = [name for name in values.get("pool", {}) if name not in BUILT_IN]
    return [*channels, *BUILT_IN, *pools, EMPTY]


def targets(values: Mapping[str, Any]) -> list[str]:
    """What `present(...)` can ask about: the channels and the pools (the built-in ones too)."""
    return [name for name in choices(values) if name != EMPTY]


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
