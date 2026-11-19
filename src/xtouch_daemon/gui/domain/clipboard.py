"""
Entries of the file as text for the clipboard, so a text editor gets valid TOML and TOML copied from the file can be
pasted: channels, pools and states as their tables (`[channel.mic]`), candidates as the values of the list of a slot
(`"browser if call"`).
"""

import re
import tomllib
from collections.abc import Mapping
from typing import Any

from xtouch_daemon.gui.domain.channels import free_id, stack_of
from xtouch_daemon.gui.domain.slot_stacks import Row, row_of
from xtouch_daemon.gui.domain.slots_document import toml_text, value_text

type Tables = dict[str, dict[str, dict[str, Any]]]
"""Tables by section and id: `{"channel": {"mic": {"type": "input"}}}`."""

_NUMBER = re.compile(r"_\d+$")


def tables_text(tables: Tables) -> str:
    """Tables as in the file: `[channel.mic]` and its options."""
    return toml_text(dict(tables))


def parse_tables(text: str, sections: tuple[str, ...]) -> Tables:
    """The tables of `sections` in a text (`[channel.mic]`, ...); none when it is no TOML or has none of them."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    found: Tables = {}
    for section in sections:
        entries = data.get(section)
        if isinstance(entries, dict):
            tables = {name: table for name, table in entries.items() if isinstance(table, dict)}  # pyright: ignore[reportUnknownVariableType]
            if tables:
                found[section] = tables  # pyright: ignore[reportArgumentType]
    return found


def pasted_id(taken: Mapping[str, Any] | set[str], name: str) -> str:
    """The id of a pasted table: its own, or one after it while that is taken (a copy of `mic_2` is `mic_3`)."""
    return name if name not in taken else free_id(taken, _NUMBER.sub("", name))


def candidates_text(candidates: list[Row]) -> str:
    """Candidates as values of the list of a slot, a line each: `"browser if call",`; one without the comma."""
    return ",\n".join(value_text(candidate.entry()) for candidate in candidates)


def parse_candidates(text: str) -> list[Row]:
    """
    The candidates in a text: values of the list of a slot (`"browser if call", { show = "mic" }`), or slots as in
    the file (`3 = [...]`, `[slots]`); none when it has none.
    """
    try:
        entries: list[Any] = tomllib.loads(f"candidates = [\n{text}\n]")["candidates"]
    except tomllib.TOMLDecodeError:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return []
        slots = data.get("slots", data)
        entries = [entry for stack in slots.values() for entry in stack_of(stack)] if isinstance(slots, dict) else []  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    return [
        row_of(entry) for entry in entries if isinstance(entry, str) or (isinstance(entry, dict) and "show" in entry)
    ]
