"""
The logic of the field of a button (`select`, `rec`, `solo`, and `mute` of a `custom` channel, and the buttons of
`[controls]`): what a press does, what a hold does and what its LED shows, each a text of a list; unset, each shows
what the strip type does by default. A program is a table in the file and a text in the list: `launch: mumble`,
`run: sysctrl display reset`, `watch: led-state --follow`; so is a service of Home Assistant a press calls
(`service: light.toggle`) and an entity an LED shows (`entity: light.desk`). A button of `[controls]` (`claim`) has a
press and an LED only, and a text or a program alone is its press.

QML keeps the texts of the parts and the tables it keeps for them (`kept`); this turns the value of the file into
those, them into the value, and says what to show.
"""

import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from xtouch_daemon.config.bindings import ServiceAction
from xtouch_daemon.config.buttons import ButtonSetup, describe_action, table_of
from xtouch_daemon.gui.domain.places import HOME_ASSISTANT_KEYS, PROGRAM_KEYS, program_text
from xtouch_daemon.gui.domain.schema import Kind, Option

PART_TITLES = {"press": "Press", "hold": "Hold", "led": "LED"}
"""The names of the parts of a button, for people."""
PROGRAM_MEANINGS = {
    "launch": "Starts the program.",
    "run": "Runs the program to its end. `{value}` is the value of the fader, else of the encoder.",
    "watch": "Lit while the program's newest line is `on`, `1`, `true` or `yes`; it flashes on `flash`.",
    "poll": "Lit while the last line of the program's last run is `on`, `1`, `true` or `yes`; it flashes on `flash`.",
    "service": "Calls the service of Home Assistant, with the entity and the data below.",
    "entity": "Lit while the entity of Home Assistant is `on`, `open`, `playing` or `home`.",
}


def parts_of(name: str, value: object, claim: bool = False) -> dict[str, Any]:
    """
    The parts of a button in the file (see `table_of`): {} for a value that is no table. Of a button of `[controls]`
    (`claim`), an action alone (a text, `{ launch }`, `{ run }`) is the press.
    """
    if claim:
        if isinstance(value, str) or (isinstance(value, Mapping) and {"launch", "run", "service"} & set(value)):  # pyright: ignore[reportUnknownArgumentType]
            return {"press": value}
        return dict(value) if isinstance(value, Mapping) else {}  # pyright: ignore[reportUnknownArgumentType]
    table = table_of(name, value)
    return dict(table) if isinstance(table, Mapping) else {}  # pyright: ignore[reportUnknownArgumentType]


def program_table(text: str) -> dict[str, Any] | None:
    """
    The table of a text typed as `run: prog arg` (or `launch:`, `watch:`, `poll:`), `service: light.toggle` or `entity:
    light.desk`; None for other text.
    """
    key, colon, rest = text.partition(":")
    if colon and key.strip() in HOME_ASSISTANT_KEYS:
        return {key.strip(): rest.strip()}
    if not colon or key.strip() not in PROGRAM_KEYS:
        return None
    try:
        command = shlex.split(rest)
    except ValueError:
        # an open quote: the program as it is, its problem says what is wrong
        command = rest.split()
    return {key.strip(): command}


@dataclass
class ButtonLogic:
    """
    The button `name` with its `columns` (press, hold and led, or press and led). `defaults` tells what the strip type
    does without a table, `extra` the actions of the modes and states there are, `inherited` the placeholder of an
    unset part at a place ("As on the channel: muted").
    """

    name: str
    columns: tuple[Option, ...]
    claim: bool = False
    defaults: Callable[[], ButtonSetup] = ButtonSetup
    extra: Callable[[], list[str]] = list
    inherited: Callable[[str], str] | None = None

    def load(self, value: object) -> tuple[dict[str, str], dict[str, Any]]:
        """The texts of the parts for the value in the file, and the tables kept for the parts that are programs."""
        parts = parts_of(self.name, value, self.claim)
        texts: dict[str, str] = {}
        kept: dict[str, Any] = {}
        for column in self.columns:
            part = parts.get(column.name)
            if isinstance(part, Mapping):
                kept[column.name] = dict(part)  # pyright: ignore[reportUnknownArgumentType]
                part = program_text(part)  # pyright: ignore[reportUnknownArgumentType]
            texts[column.name] = "" if part is None else str(part)
        return texts, kept

    def items(self, column: Option) -> list[tuple[str, str]]:
        """What the list of a part offers, with what each means (the text is the meaning of the program's key)."""
        choices = [*column.choices, *(name for name, _ in column.meanings if name not in column.choices)]
        if column.kind == Kind.ACTION:
            choices += [extra for extra in self.extra() if extra not in choices]
        if self.model_of(column) is not None:
            # a service, an entity: picked, the rest of its options shows below
            choices.append(self.marker_of(column) + ":")
        return [
            (choice, column.meaning(choice) or PROGRAM_MEANINGS.get(choice.removesuffix(":"), "")) for choice in choices
        ]

    @staticmethod
    def model_of(column: Option) -> object:
        return ServiceAction if column.kind == Kind.ACTION else column.entity

    @staticmethod
    def marker_of(column: Option) -> str:
        return "service" if column.kind == Kind.ACTION else "entity"

    def value(self, texts: Mapping[str, str], kept: Mapping[str, Any]) -> dict[str, Any] | str | bool | None:
        """The table of the button for the texts of the parts (or its short form); None for none of them set."""
        table: dict[str, Any] = {}
        for column in self.columns:
            name = column.name
            text = texts.get(name, "").strip()
            held = kept.get(name)
            if held is not None and text == program_text(held):
                table[name] = held
            elif (program := program_table(text)) is not None:
                key = next(iter(program))
                # another service or entity typed: its other options stay
                table[name] = {**held, **program} if held is not None and key in held else program
            elif text:
                table[name] = text
        if self.claim:
            # the short form of `[controls]`: the press alone, e.g. `rec = "toggle:call"`
            return table["press"] if set(table) == {"press"} else table or None
        # the shorthands where they say it all: `rec = "muted"`, `select = false`
        if self.name != "select" and set(table) == {"led"} and isinstance(table["led"], str):
            return table["led"]
        if self.name == "select" and table == {"press": "off"}:
            return False
        return table or None

    def kept_of(self, value: object) -> dict[str, Any]:
        """The tables of the parts that are programs, services or entities in a value."""
        parts = parts_of(self.name, value, self.claim)
        return {name: dict(part) for name, part in parts.items() if isinstance(part, Mapping)}  # pyright: ignore[reportUnknownArgumentType]

    def placeholder(self, column: Option) -> str:
        if self.inherited is not None:
            return self.inherited(column.name)
        default = getattr(self.defaults(), column.name)
        return f"default: {describe_action(default) if column.kind == Kind.ACTION else default}"

    def unknown(self, texts: Mapping[str, str]) -> set[str]:
        """Parts of a list whose text is none of its items: they mean nothing (their problem says why)."""
        return {
            column.name
            for column in self.columns
            if column.kind not in (Kind.ACTION, Kind.BINDING)
            and texts.get(column.name, "").strip()
            and texts[column.name].strip() not in [text for text, _ in self.items(column)]
        }

    def meaning(self, texts: Mapping[str, str]) -> str:
        """What the parts that are set (or their defaults) mean, in one text with the parts in `code`."""
        unknown = self.unknown(texts)
        defaults = self.defaults()
        lines: list[str] = []
        for column in self.columns:
            text = texts.get(column.name, "").strip()
            if not text and (column.name in unknown or self.inherited is not None):
                continue
            shown = text or describe_action(getattr(defaults, column.name))
            program = program_table(shown)
            meaning = column.meaning(shown) or (
                PROGRAM_MEANINGS[next(iter(program))]
                if program is not None
                else "Picks the mode."
                if shown.startswith("mode:")
                else "Turns the state or mode on and back."
                if shown.startswith("toggle:")
                else ""
            )
            if meaning and shown != "off":
                lines.append(f"{PART_TITLES.get(column.name, column.title)} `{shown}`: {meaning}")
        return " ".join(lines)

    def view(self, texts: Mapping[str, str], kept: Mapping[str, Any]) -> dict[str, Any]:
        """What the field shows for the texts: the parts with their items and placeholders, and the meaning."""
        parts: list[dict[str, Any]] = []
        for column in self.columns:
            model = self.model_of(column)
            held = kept.get(column.name)
            parts.append(
                {
                    "name": column.name,
                    "title": PART_TITLES.get(column.name, column.title),
                    "tip": column.help,
                    "editable": column.kind in (Kind.ACTION, Kind.BINDING),
                    "placeholder": self.placeholder(column),
                    "items": [{"text": text, "meaning": meaning} for text, meaning in self.items(column)],
                    "marker": self.marker_of(column) if model is not None else "",
                    # the options of the service or entity of the part, while it is one
                    "table": dict(held)
                    if model is not None and held is not None and self.marker_of(column) in held
                    else None,
                }
            )
        return {"parts": parts, "meaning": self.meaning(texts)}
