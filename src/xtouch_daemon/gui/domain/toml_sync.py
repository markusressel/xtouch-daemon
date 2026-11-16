"""
Writing the drafts back into the TOML text of the file: options that did not change keep their comments and
formatting, strips and layouts that stay where they were keep their tables, and the options kept for other types are
comments in their strip's table.
"""

import copy
import re
from dataclasses import dataclass
from typing import Any

import tomlkit
import tomlkit.exceptions
from tomlkit.container import Container
from tomlkit.items import Comment, Item, Null, Table, Whitespace

from xtouch_daemon.gui.domain.drafts import KEPT_HEADER, SECTIONS, LayoutDraft, StripDraft

ORDER = (
    *(name for name, section in SECTIONS.items() if not section.optional),
    "aliases",
    "strip",
    *(name for name, section in SECTIONS.items() if section.optional),
    "layout",
)
"""Where a new section goes in the file: optional ones like `[mqtt]` at the end, like in the example."""


_KEPT = re.compile(r'#\s*kept from type = "([^"\\]*)"')


def _sync_items(
    table: Container | Table, values: dict[str, Any], looks: dict[str, Item] | None = None, keep: tuple[str, ...] = ()
) -> None:
    """
    Makes the options of the table the values, leaving the ones that did not change (and their comments) alone, and
    those in `keep` (e.g. the strips of a layout, synced by themselves). An added option takes its look from `looks`
    (e.g. a value on several lines) if it has the same value there.
    """
    for name in [name for name in table if name not in values and name not in keep]:
        del table[name]
    current = table.unwrap()
    for name, value in values.items():
        if name in current and current[name] != value:
            table[name] = value
    added = {name: value for name, value in values.items() if name not in current}
    if added:
        # after the last option, not after the comments and blank lines that end the table
        trailing = _trim(table)
        for name, value in added.items():
            look = (looks or {}).get(name)
            table[name] = copy.deepcopy(look) if look is not None and look.unwrap() == value else value
        for item in trailing:
            table.add(item)


def sync_section(toml: tomlkit.TOMLDocument, name: str, values: dict[str, Any]) -> tomlkit.TOMLDocument:
    if name in toml:
        _sync_items(toml[name], values)  # pyright: ignore[reportArgumentType]: a section is a table
        return toml
    if not values:
        return toml
    table = tomlkit.table()
    _sync_items(table, values)
    # before the sections that follow it, rather than at the end after the strips
    later = ORDER[ORDER.index(name) + 1 :]
    rebuilt = tomlkit.document()
    for key, item in toml.body:
        if key is not None and key.key in later and name not in rebuilt:
            table.add(tomlkit.nl())
            rebuilt.append(name, table)
        if key is None:
            rebuilt.add(item)  # pyright: ignore[reportArgumentType]: a comment or whitespace
        else:
            rebuilt.append(key, item)
    if name not in rebuilt:
        rebuilt.append(name, table)
    return rebuilt


def are_tables(value: object) -> bool:
    """Whether the value is a list of tables."""
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)  # pyright: ignore[reportUnknownVariableType]


def sync_layouts(toml: tomlkit.TOMLDocument, layouts: list[LayoutDraft]) -> None:
    """Like `sync_strips`: the layouts that stay where they were keep their tables, comments and formatting."""
    tables: Any = toml.get("layout", [])
    if [layout.origin for layout in layouts] == list(range(len(tables))):
        for layout, table in zip(layouts, tables, strict=True):
            _sync_items(table, layout.values, keep=("strip",))
            sync_strips(table, layout.strips)
        return
    aot = tomlkit.aot()
    for layout in layouts:
        table = copy.deepcopy(tables[layout.origin]) if layout.origin is not None else tomlkit.table()
        _sync_items(table, layout.values, keep=("strip",))
        sync_strips(table, layout.strips)
        aot.append(table)
    if not layouts:
        del toml["layout"]
    elif "layout" in toml:
        toml["layout"] = aot
    else:
        toml.append("layout", aot)


def sync_strips(toml: tomlkit.TOMLDocument | Table, strips: list[StripDraft]) -> None:
    tables: Any = toml.get("strip", [])
    if [strip.origin for strip in strips] == list(range(len(tables))):
        for strip, table in zip(strips, tables, strict=True):
            _sync_strip(table, strip)
        return
    aot = tomlkit.aot()
    for strip in strips:
        table = copy.deepcopy(tables[strip.origin]) if strip.origin is not None else tomlkit.table()
        _sync_strip(table, strip)
        # the blank lines after it were for its old place, the array of tables puts one between its tables
        for item in _trim(table):
            if not isinstance(item, Whitespace):
                table.add(item)
        aot.append(table)
    if not strips:
        # the file has strips (without any, nothing changed and the loop above returned), and all of them went
        del toml["strip"]
    elif "strip" in toml:
        toml["strip"] = aot
    else:
        toml.append("strip", aot)


def _sync_strip(table: Table, strip: StripDraft) -> None:
    """The options of the strip, and the comments with the options kept for other types."""
    blocks = _kept_blocks(table)
    # an option keeps the look it had in the file (e.g. profiles on several lines), going into a comment and back
    bodies = [block.options.body for block in blocks if block.options is not None] + [table.value.body]
    looks = {key.key: item for body in bodies for key, item in body if key is not None}
    unchanged = {
        block.kind: block.lines for block in blocks if block.readable and strip.kept.get(block.kind) == block.values
    }
    written = [unchanged.get(kind) or _kept_lines(kind, values, looks) for kind, values in strip.kept.items() if values]
    _sync_items(table, strip.values, looks)
    removed = [line for block in blocks if block.readable for line in block.lines]
    body = table.value.body
    for index, (key, item) in enumerate(body):
        if key is None and any(item is line for line in removed):
            # in place, like tomlkit removes items, so the indices of the options stay right
            body[index] = (None, Null())
    trailing = _trim(table)
    for lines in written:
        for line in lines:
            table.add(line)
    for item in trailing:
        table.add(item)


@dataclass
class _KeptBlock:
    """A comment with the options kept for a type (see `KEPT_HEADER`)."""

    kind: str
    lines: list[Comment]
    options: tomlkit.TOMLDocument | None
    """The options, None when the comment is no TOML."""

    @property
    def readable(self) -> bool:
        return self.options is not None

    @property
    def values(self) -> dict[str, Any]:
        return {} if self.options is None else self.options.unwrap()


def _kept_blocks(table: Table) -> list[_KeptBlock]:
    """The comments with kept options in the table: a header line, and the lines that follow it."""
    blocks: list[_KeptBlock] = []
    lines: list[Comment] = []
    for key, item in [*table.value.body, (None, Null())]:
        comment = item if key is None and isinstance(item, Comment) else None
        text = None if comment is None else comment.as_string().strip()
        if lines and (text is None or _KEPT.match(text)):
            kind = _KEPT.match(lines[0].as_string().strip())[1]  # pyright: ignore[reportOptionalSubscript]: a header
            source = "\n".join(re.sub(r"^# ?", "", line.as_string().strip()) for line in lines[1:]) + "\n"
            try:
                options: tomlkit.TOMLDocument | None = tomlkit.parse(source)
            except tomlkit.exceptions.ParseError:
                options = None
            blocks.append(_KeptBlock(kind, lines, options))
            lines = []
        if comment is not None and text is not None and (lines or _KEPT.match(text)):
            lines.append(comment)
    return blocks


def _kept_lines(kind: str, values: dict[str, Any], looks: dict[str, Item]) -> list[Comment]:
    """The comment lines that keep the options of a type."""
    document = tomlkit.document()
    for name, value in values.items():
        look = looks.get(name)
        document.add(name, copy.deepcopy(look) if look is not None and look.unwrap() == value else _inline(value))
    text = tomlkit.dumps(document)
    return [tomlkit.comment(line) for line in (KEPT_HEADER.format(type=kind)[2:], *text.splitlines())]


def _inline(value: Any) -> Item:
    """A value that fits on the lines of a comment: tables inline, a list of tables on a line each."""
    if isinstance(value, dict):
        table = tomlkit.inline_table()
        for name, item in value.items():
            table[name] = _inline(item)
        return table
    if isinstance(value, list | tuple):
        array = tomlkit.array()
        for item in value:
            array.append(_inline(item))
        return array.multiline(any(isinstance(item, dict) for item in value))
    return tomlkit.item(value)


def draft_of(values: dict[str, Any], origin: int, table: Table) -> StripDraft:
    """A strip as it is in the file, with the options it keeps for other types."""
    kept: dict[str, dict[str, Any]] = {}
    unreadable: list[str] = []
    for block in _kept_blocks(table):
        if block.readable:
            kept[block.kind] = kept.get(block.kind, {}) | block.values
        else:
            unreadable.append(block.kind)
    return StripDraft(values, origin, kept, tuple(unreadable))


def _trim(table: Container | Table) -> list[Any]:
    """
    Takes the comments and blank lines at the end of the table out of it, and returns them. The places of removed
    options (`Null`, tomlkit removes in place) there go away: they can't be added again.
    """
    body = table.body if isinstance(table, Container) else table.value.body
    trailing: list[Any] = []
    # keyless items at the end are in no index of the table, taking them out leaves it intact
    while body and body[-1][0] is None:
        trailing.insert(0, body.pop()[1])
    return [item for item in trailing if not isinstance(item, Null)]
