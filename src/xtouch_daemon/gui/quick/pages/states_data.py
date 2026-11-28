"""
What the page States shows, as plain data for QML: the words of its sources and menus, the rows of its list, the
segments of "Kind", "On while" and the override, and the entries of the menus Add and Add source. No Qt here:
`StatesPage` puts them into models and properties, the tests read them directly.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from xtouch_daemon.gui.domain.slots_document import Validation
from xtouch_daemon.gui.domain.states import OVERRIDES, live_state, ordered
from xtouch_daemon.gui.quick.pages.slots_data import rich
from xtouch_daemon.live.messages import Snapshot

SOURCES = {
    "apps": "An application plays",
    "recording": "An application records",
    "voice_chat": "You are in the voice chat",
    "processes": "A process runs",
    "devices": "A device is there",
    "channels": "A channel is present",
    "homeassistant": "A switch in Home Assistant is on",
    "command": "A program of your own says on",
}
"""The sources of a state, in the words of the menu Add source."""
SOURCE_DETAILS = {
    "apps": "You list the applications, e.g. `@games`.",
    "recording": "You list the applications, e.g. `@voip` for an open microphone.",
    "voice_chat": "On during a call, e.g. in a channel of Mumble.",
    "processes": "You list the names of the programs, e.g. `@steam-games`.",
    "devices": "You list outputs or inputs, e.g. a USB headset that is plugged in.",
    "channels": "You list channels of the file, e.g. one for a device that comes and goes.",
    "homeassistant": "A switch for the state in Home Assistant turns it on. Needs `[mqtt]`.",
    "command": "A program prints `on` while the state should be, e.g. a check of your VPN.",
}
"""What each source of the menu Add source asks for, under its words."""
SOURCE_ICONS = {
    "apps": "play-circle-outline",
    "recording": "record-circle-outline",
    "voice_chat": "headset",
    "processes": "cog-outline",
    "devices": "headphones",
    "channels": "tune-vertical",
    "homeassistant": "home-assistant",
    "command": "console",
}
"""The icons of the sources in the menu Add source."""
MODE_ICON = "view-dashboard-outline"
STATE_ICON = "toggle-switch-outline"
SWITCHES = frozenset({"voice_chat", "homeassistant"})
"""Sources that are a switch: added, they are on."""
MODE_ONLY = ("label", "priority")
DELAYS = ("delay_on", "delay_off", "persist")
KIND_HELP = (
    "One mode is on at a time: the one with the highest priority whose sources are on. Any number of states can be on."
)
ON_WHILE_HELP = "Sources are what goes on at the computer. A condition combines other states and modes."
WHEN_HELP = "On while this condition of other states and modes holds."
NO_SOURCES = "No sources yet: it is on only while you turn it on. Add source adds one."
SOME_SOURCES = "On while any of these is on."
NOT_USED = "No slot or control asks about it yet."
EMPTY = (
    "No states yet. A state is when something matters: slots can show a channel only while it is on "
    '("voip if call"). Add makes one; "In a call" and "Gaming" in its menu start from the usual '
    "ones. Slots work without any."
)
HINT = (
    "What slots show depends on them: a mode at a time (the one with the highest priority whose sources "
    "are on), and any number of states."
)
TEMPLATES: tuple[tuple[str, str, bool, dict[str, Any], str], ...] = (
    (
        "In a call",
        "call",
        False,
        {"voice_chat": True, "recording": ["@voip"], "delay_off": 5},
        "A state: on while you are in the voice chat or an application for calls records.",
    ),
    (
        "Gaming",
        "gaming",
        True,
        {"label": "Gaming", "processes": ["@steam-games"]},
        "A mode: on while a game of Steam runs. The LCDs show Gaming when it comes.",
    ),
)
"""The starting points in the menu Add: text, id, whether a mode, the options, and what it is."""
KINDS = (
    ("Mode", True, "One mode is on at a time. Slots and controls can change with it, e.g. for a game."),
    ("State", False, "Any number of states can be on at once. A slot can show a channel only while one is on."),
)
"""The kinds in the menu Add: text, whether a mode, and what it is."""

Row = tuple[str, dict[str, Any]]


def is_set(value: Any) -> bool:
    """Whether a source has a value: a list with something in it, or a switch that is on."""
    return value is not None and value is not False and value != [] and value != ()


def list_rows(states: Mapping[str, Any], validation: Validation, snapshot: Snapshot | None) -> list[Row]:
    """The modes, then the other states: the name (or label), what it is, whether it has problems, the live value."""
    rows: list[Row] = []
    for name in ordered(states):
        state = states[name] if isinstance(states[name], Mapping) else {}
        mode = bool(state.get("mode"))
        live = live_state(snapshot, name)
        rows.append(
            (
                name,
                {
                    "kind": "mode" if mode else "state",
                    "name": name,
                    "title": str(state.get("label") or name),
                    "tags": "",
                    "below": rich("mode" if mode else "state"),
                    "icon": MODE_ICON if mode else STATE_ICON,
                    "tip": "",
                    "problem": bool(validation.at("state", name)),
                    # the dot after the name: on, off, or none while no daemon tells
                    "dot": None if live is None else live.value,
                },
            )
        )
    return rows


def segments(texts: Sequence[tuple[str, str]], checked: str | None) -> list[dict[str, Any]]:
    """Segments of a row of buttons of which one is checked: `[(value, text), ...]`."""
    return [{"value": value, "text": text, "checked": value == checked, "visible": True} for value, text in texts]


def override_segments(mode: bool, name: str, state: Any, picked: str | None) -> list[dict[str, Any]]:
    """
    The override of a state as `auto`, `on`, `off`; of a mode: `auto` and `pick` (a mode is picked, not overridden;
    none is checked while another mode is picked). Shown only while the daemon tells about the state.
    """
    if mode:
        current = "on" if picked == name else "auto" if picked is None else None
    else:
        current = state.override if state is not None else None
    return [
        {
            "value": value,
            "text": "pick" if mode and value == "on" else value,
            "checked": value == current,
            "visible": state is not None and (not mode or value != "off"),
        }
        for value in OVERRIDES
    ]


def add_menu() -> list[dict[str, Any]]:
    """What Add offers: a mode, a state, and the usual ones to start from."""
    kinds = [
        {
            "action": f"kind:{'mode' if mode else 'state'}",
            "text": text,
            "icon": MODE_ICON if mode else STATE_ICON,
            "detail": rich(detail),
        }
        for text, mode, detail in KINDS
    ]
    templates = [
        {
            "action": f"template:{name}",
            "text": text,
            "icon": MODE_ICON if mode else STATE_ICON,
            "detail": rich(detail),
        }
        for text, name, mode, _, detail in TEMPLATES
    ]
    return [{"title": "Kinds", "items": kinds}, {"title": "Starting points", "items": templates}]


def source_menu(shown: Sequence[str]) -> list[dict[str, Any]]:
    """The menu Add source: the sources the state does not show yet."""
    return [
        {
            "title": "Add source",
            "items": [
                {"action": source, "text": text, "icon": SOURCE_ICONS[source], "detail": rich(SOURCE_DETAILS[source])}
                for source, text in SOURCES.items()
                if source not in shown
            ],
        }
    ]
