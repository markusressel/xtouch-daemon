"""
`device` and `choices` of an output or input channel as one list: the devices of the strip, each of which can have a
label, a profile of its sound card and a volume range. While none has any of them, the list is `device`; once one
has, it is `choices`.
"""

from collections.abc import Callable, Mapping
from typing import Any

from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.qt.fields.basics import TableSuggest
from xtouch_daemon.gui.qt.fields.option_row import OptionRow

DEVICE_HELP = (
    "The devices, by node name or description (`xtouch-daemon list-devices`); none: the default device. With several "
    "(or wildcards like `bluez_output.*`), the strip shows the default one, and Select switches between them. ✎ gives "
    "an entry a label for the LCD, a profile of its sound card or a volume range; then each entry is one step of "
    "Select, the first of its devices that is there."
)

type Entry = dict[str, Any]


def entries_of(device: object, choices: object) -> list[Entry]:
    """The list of the row, from `device` (a name or a list of them) or `choices` (tables) of the file."""
    if isinstance(choices, list | tuple) and choices:
        return [dict(choice) for choice in choices if isinstance(choice, Mapping)]
    names = (device,) if isinstance(device, str) else device if isinstance(device, list | tuple) else ()
    return [{"device": name} for name in names]


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


def device_row(
    device: Option,
    choices: Option,
    get: Callable[[str], Any],
    put: Callable[[str, Any], None],
    suggest: TableSuggest | None,
    link: str | None = None,
) -> OptionRow:
    """
    The row of the devices: `get(name)` reads `device` or `choices`, `put(name, value)` sets one (None: unsets it).
    Its problems are those of both.
    """
    option = Option("device", Kind.TABLES, DEVICE_HELP, device.default, False, columns=choices.columns)

    def shown() -> list[Entry] | None:
        return entries_of(get("device"), get("choices")) or None

    def chosen(entries: list[Entry] | None) -> None:
        names, tables = written(entries or [])
        put("device", names)
        put("choices", tables)

    row = OptionRow(option, shown, chosen, suggest, link=link)
    row.names = ("device", "choices")
    return row
