"""
The logic of a list of tables (the `choices` of a strip) and of the devices as one list (`device` and `choices`): what
an entry of the list says of itself, how the list changes, and how `device` and `choices` are written. QML draws the
cards; what they say and what an edit makes of the list is decided here.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from xtouch_daemon.gui.domain.schema import Kind, Option

type Entry = dict[str, Any]

FOLDED = ("card", "profile")
"""Columns that stay folded while unset, behind a button of their own (`FOLD_TEXT`), when the table has a `device`."""
FOLD_TEXT = "Switch the sound card first"
FOLD_TIP = (
    "A digital output (e.g. HDMI) of a card that plays analog now is a profile of its card: the daemon switches the "
    "card to it first."
)
TABLE_PLACEHOLDERS = {
    "min_volume": "the channel's",
    "max_volume": "the channel's",
    "label": "the start of the description of the device",
}
"""What an unset column takes, by name."""
HANDLE_TIP = "Drag to move it (or Ctrl+Up/Down): the order is the order they are picked in"
DEVICE_HELP = (
    "The devices, by node name or description (`xtouch-daemon list-devices`); none: the default device. With several "
    "(or wildcards like `bluez_output.*`), the strip shows the default one, and Select switches between them. ✎ gives "
    "an entry a label for the LCD, a profile of its sound card or a volume range; then each entry is one step of "
    "Select, the first of its devices that is there."
)

Describe = Callable[[str, object], str]
"""Names a value of a column of an entry in words (its detail), "" for what it does not know."""


def folds(columns: Sequence[Option]) -> bool:
    """Whether the card and profile of an entry fold: only in a table with a device, a card and a profile."""
    names = {column.name for column in columns}
    return {"device", "card", "profile"} <= names


def trim(detail: str) -> str:
    """A description without what the sound server adds: "Analog Stereo Output (active)" is "Analog Stereo Output"."""
    return detail.split(" (")[0].split(", ")[0]


def summary(entry: Mapping[str, Any], describe: Describe) -> tuple[str, list[str]]:
    """What an entry is in a line, and below it what it needs and its range, each only when it says something."""
    described = {
        name: describe(name, entry[name]) or str(entry[name])
        for name in ("label", "device", "profile", "card")
        if entry.get(name) not in (None, "")
    }
    title = described.get("label") or described.get("device") or described.get("profile") or "New"
    lines: list[str] = []
    if "label" in described and "device" in described:
        lines.append(described["device"])
    if "profile" in described and "device" in entry:
        lines.append(f'Switches its sound card to "{described["profile"]}" first')
    elif "profile" in described and "label" in described:
        lines.append(described["profile"])
    bottom, top = entry.get("min_volume"), entry.get("max_volume")
    if bottom is not None or top is not None:
        lines.append(
            f"Volume up to {top} %"
            if bottom is None
            else f"Volume from {bottom} %"
            if top is None
            else f"Volume {bottom} – {top} %"
        )
    return str(title), lines


def put(entries: list[Entry], index: int, name: str, value: Any) -> list[Entry]:
    """The list with an option of one entry set (None: removed). An index past the end adds entries."""
    result = [dict(entry) for entry in entries]
    while len(result) <= index:
        result.append({})
    if value is None:
        result[index].pop(name, None)
    else:
        result[index][name] = value
    return result


def move(entries: list[Entry], index: int, delta: int) -> tuple[list[Entry], int]:
    """The list with the entry at `index` moved by `delta` places (not past the ends), and where it is now."""
    target = max(0, min(len(entries) - 1, index + delta))
    if not entries or not 0 <= index < len(entries) or target == index:
        return [dict(entry) for entry in entries], index
    result = [dict(entry) for entry in entries]
    result.insert(target, result.pop(index))
    return result, target


def move_before(entries: list[Entry], index: int, before: int) -> tuple[list[Entry], int]:
    """The entry at `index` dropped before the one at `before` (`len(entries)`: at the end), and where it is."""
    result = [dict(entry) for entry in entries]
    if not 0 <= index < len(result):
        return result, index
    entry = result.pop(index)
    at = before - 1 if before > index else before
    at = max(0, min(len(result), at))
    result.insert(at, entry)
    return result, at


def remove(entries: list[Entry], index: int) -> list[Entry]:
    return [dict(entry) for position, entry in enumerate(entries) if position != index]


def committed(entries: list[Entry]) -> list[Entry] | None:
    """The entries for the file: those with something in them (a new one is not written before), None for none."""
    return [entry for entry in entries if entry] or None


def entries_of(device: object, choices: object) -> list[Entry]:
    """The list of the row of the devices, from `device` (a name or a list of them) or `choices` (tables)."""
    if isinstance(choices, list | tuple) and choices:
        return [dict(choice) for choice in choices if isinstance(choice, Mapping)]  # pyright: ignore[reportUnknownVariableType]
    names = (device,) if isinstance(device, str) else device if isinstance(device, list | tuple) else ()
    return [{"device": name} for name in names]  # pyright: ignore[reportUnknownVariableType]


def written(entries: list[Entry]) -> tuple[str | list[str] | None, list[Entry] | None]:
    """
    `device` and `choices` for the list (None: unset): the names alone while no entry has more than its device (one
    as a name), else the tables. Entries with nothing in them are not written.
    """
    entries = [entry for entry in entries if entry]
    if any(set(entry) - {"device"} for entry in entries):
        return None, entries
    names = [str(entry["device"]) for entry in entries]
    if not names:
        return None, None
    return names[0] if len(names) == 1 else names, None


def device_option(device: Option, choices: Option) -> Option:
    """The option of the one row of the devices."""
    return Option("device", Kind.TABLES, DEVICE_HELP, device.default, False, columns=choices.columns)
