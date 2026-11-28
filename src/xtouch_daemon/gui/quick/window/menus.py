"""
The menus of the window and their keys, as data: File, Edit, View and Help with every entry, the line under it that
says what it does, and its shortcuts. QML draws them (`AppMenuBar.qml`) and binds the shortcuts (`Main.qml`); each
entry has an `id`, which `Shell.trigger()` does. The same table gives the popover "Keyboard shortcuts".

An entry is a dict: `id`, `text`, `keys` (portable shortcuts, e.g. `Ctrl+S`), `description`, `checkable`; a
separator has `id` "-", and a submenu has `entries`.
"""

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from xtouch_daemon.gui.qt.theme.settings import ZOOM_LEVELS, zoom_text
from xtouch_daemon.gui.qt.theme.tokens import ThemeMode
from xtouch_daemon.gui.quick.window.panels import PLACE_TITLES, PLACES

type Entry = dict[str, Any]

SEPARATOR: Entry = {"id": "-"}
Std = QKeySequence.StandardKey


def keys_of(*keys: Std | str) -> list[str]:
    """The shortcuts of a standard key on this platform and of plain sequences, as `Shortcut` takes them."""
    found: list[str] = []
    for key in keys:
        if isinstance(key, str):
            found.append(QKeySequence(key).toString())
            continue
        # not the keys of the media keyboards some platforms list (a Save key)
        found += [sequence.toString() for sequence in QKeySequence.keyBindings(key) if _is_typed(sequence)]
    return list(dict.fromkeys(found))


def _is_typed(sequence: QKeySequence) -> bool:
    """Whether `sequence` is typed on a plain keyboard: with Ctrl or Alt, or a function key or Delete."""
    if sequence.isEmpty():
        return False
    first = sequence[0]
    typed = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
    return (
        bool(first.keyboardModifiers() & typed)
        or first.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        or (Qt.Key.Key_F1 <= first.key() <= Qt.Key.Key_F35)
    )


def native(sequence: str) -> str:
    """A shortcut as the desktop writes it (`Ctrl+S`)."""
    return QKeySequence(sequence).toString(QKeySequence.SequenceFormat.NativeText)


def entry(id: str, text: str, *keys: Std | str, description: str = "", checkable: bool = False) -> Entry:
    found = keys_of(*keys)
    shortcut = native(found[0]) if found else ""
    return {
        "id": id,
        "text": text,
        "keys": found,
        "shortcut": shortcut,
        "description": description,
        "checkable": checkable,
    }


def submenu(text: str, entries: list[Entry]) -> Entry:
    return {"id": "+", "text": text, "keys": [], "entries": entries}


def plain(text: str) -> str:
    """`text` without its mnemonic marker (`&Save` is `Save`)."""
    return text.replace("&", "")


def mnemonic(text: str) -> str:
    """The letter after the `&` of `text`, lower case; "" for none."""
    at = text.find("&")
    return text[at + 1].lower() if 0 <= at < len(text) - 1 else ""


def place_entries(panel: str) -> list[Entry]:
    return [entry(f"{panel}.place.{place}", PLACE_TITLES[place], checkable=True) for place in PLACES]


def menus(rail: list[tuple[str, str]]) -> list[Entry]:
    """
    The menus; `rail` has the name and title of each page of the rail (Ctrl+1 for the first). A menu is an entry
    with `entries`; its title has the mnemonic of Alt+<letter>.
    """
    pages = [entry(f"page.{name}", f"&{title}", f"Ctrl+{number}") for number, (name, title) in enumerate(rail, start=1)]
    return [
        {
            "id": "file",
            "text": "&File",
            "entries": [
                entry("save", "&Save and apply", Std.Save),
                entry("revert", "&Revert"),
                SEPARATOR,
                entry("quit", "&Quit", Std.Quit),
            ],
        },
        {
            "id": "edit",
            "text": "&Edit",
            "entries": [
                entry("undo", "&Undo", Std.Undo),
                entry("redo", "&Redo", Std.Redo),
                SEPARATOR,
                # for the entry picked in the list of the page (a candidate, a channel, a state) while the list has
                # the focus; off in a field, where the keys edit its text
                entry("cut", "Cu&t", Std.Cut),
                entry("copy", "&Copy", Std.Copy),
                entry("paste", "&Paste", Std.Paste),
                entry("duplicate", "&Duplicate", "Ctrl+D"),
                entry("remove", "Re&move", Std.Delete, "Backspace"),
                entry("rename", "Re&name", "F2"),
            ],
        },
        {
            "id": "view",
            "text": "&View",
            "entries": [
                *pages,
                SEPARATOR,
                entry(
                    "device",
                    "&Device",
                    description="The window with the device: what it shows right now, or what Simulate shows",
                    checkable=True,
                ),
                entry(
                    "log",
                    "&Log",
                    "Ctrl+L",
                    description="The log of the daemon that runs, as the journal or its terminal show it",
                    checkable=True,
                ),
                submenu("Device &at", place_entries("device")),
                submenu("Log a&t", place_entries("log")),
                entry("labels", "&Names of the pages", checkable=True),
                SEPARATOR,
                submenu(
                    "&Theme",
                    [entry(f"theme.{mode.value}", mode.value.capitalize(), checkable=True) for mode in ThemeMode],
                ),
                submenu(
                    "&Zoom",
                    [
                        # Ctrl++ on keyboards with a + key, Ctrl+= where + is Shift+=
                        entry("zoom.in", "Zoom &in", Std.ZoomIn, "Ctrl+="),
                        entry("zoom.out", "Zoom &out", Std.ZoomOut),
                        entry("zoom.reset", "&Actual size", "Ctrl+0"),
                        SEPARATOR,
                        *(entry(f"zoom.{level:g}", zoom_text(level), checkable=True) for level in ZOOM_LEVELS),
                    ],
                ),
            ],
        },
        {
            "id": "help",
            "text": "&Help",
            "entries": [
                entry("docs", "&Documentation", Std.HelpContents),
                entry("keys", "&Keyboard shortcuts"),
            ],
        },
    ]


def flat(entries: list[Entry]) -> list[Entry]:
    """Every entry of the menus, those of the submenus too, without separators and submenus themselves."""
    found: list[Entry] = []
    for item in entries:
        if "entries" in item:
            found += flat(item["entries"])
        elif item["id"] not in ("-", "+"):
            found.append(item)
    return found
