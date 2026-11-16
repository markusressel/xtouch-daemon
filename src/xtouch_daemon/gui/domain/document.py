"""
A configuration file being edited: its options as plain data the editor changes, validated with the pydantic models
of the configuration, and written back into the original TOML text, so comments and formatting of the user stay
where they can.
"""

import copy
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
import tomlkit.exceptions
from pydantic import ValidationError
from tomlkit.container import Container
from tomlkit.items import Comment, Item, Null, Table, Whitespace

from xtouch_daemon import protocol
from xtouch_daemon.config import DEFAULT_LAYOUT, Config, ConfigError, Problem, example_config, problems_of
from xtouch_daemon.gui.domain.schema import Section, sections, strip_models

SECTIONS: dict[str, Section] = {section.name: section for section in sections()}
"""The sections with options of their own (`[device]`, `[behavior]`, `[mqtt]`), edited option by option."""

RESTART_SECTIONS: dict[str, str | None] = {"device": "name", "mqtt": None}
"""The sections a reload does not take, with the one option of them that matters (None: all of them)."""
"""What a reload does not change: the daemon keeps the device it opened, and its configuration on a new `[mqtt]`."""

ORDER = (
    *(name for name, section in SECTIONS.items() if not section.optional),
    "aliases",
    "strip",
    *(name for name, section in SECTIONS.items() if section.optional),
    "layout",
)
"""Where a new section goes in the file: optional ones like `[mqtt]` at the end, like in the example."""

type OptionPath = tuple[int | str, ...]
"""Where an option is in the TOML data, like `Problem.path`, e.g. `("strip", 2, "label")`."""


KEPT_HEADER = '# kept from type = "{type}" (the GUI restores these when the strip is switched back):'
"""
The first line of the comment that keeps the options of a type the strip had before (see `StripDraft.kept`), followed
by the options as TOML, each line commented out.
"""

_KEPT = re.compile(r'#\s*kept from type = "([^"\\]*)"')


@dataclass
class StripDraft:
    """A strip being edited: its options as in the file."""

    values: dict[str, Any]
    origin: int | None = None
    """Its position in the file when it was read, which keeps its comments and formatting when it moves."""
    kept: dict[str, dict[str, Any]] = field(default_factory=dict)
    """
    The options of the types the strip had before that its type does not have, by type, so switching back restores
    them. They are in the file as comments in the strip's table (`KEPT_HEADER`), which the daemon ignores.
    """
    unreadable: tuple[str, ...] = ()
    """The types whose kept options in the file are no TOML (e.g. edited by hand): they stay there as they are."""

    @property
    def type(self) -> str | None:
        return self.values.get("type")


@dataclass
class LayoutDraft:
    """A layout (`[[layout]]`) being edited: its own options as in the file, and its strips."""

    values: dict[str, Any]
    strips: list[StripDraft]
    origin: int | None = None
    """Its position in the file when it was read, which keeps its comments and formatting."""

    @property
    def name(self) -> str:
        name = self.values.get("name")
        return name if isinstance(name, str) else ""

    def data(self) -> dict[str, Any]:
        return self.values | ({"strip": [strip.values for strip in self.strips]} if self.strips else {})


@dataclass(frozen=True)
class DocumentState:
    """Everything the editor changes in a document, for undo (see `ConfigDocument.state()`)."""

    sections: dict[str, dict[str, Any] | None]
    aliases: list[tuple[str, str]]
    strips: list[StripDraft]
    extra: dict[str, Any]
    layouts: list[LayoutDraft] = field(default_factory=list[LayoutDraft])
    layout: int | None = None

    def data(self) -> dict[str, Any]:
        """What the configuration is in this state, as `ConfigDocument.data()` (to compare states)."""
        return {
            "sections": self.sections,
            "aliases": self.aliases,
            "strips": [strip.values for strip in self.strips],
            "layouts": [layout.data() for layout in self.layouts],
            "layout": self.layout,
        }


@dataclass(frozen=True)
class Validation:
    config: Config | None
    """The configuration, None while it has problems."""
    problems: list[Problem] = field(default_factory=list)

    def at(self, *path: int | str) -> list[Problem]:
        """The problems of an option, or of a section or strip and everything in it."""
        return [problem for problem in self.problems if problem.path[: len(path)] == path]


class ConfigDocument:
    """
    The configuration file at `path`, or the example configuration when there is no file yet. The editor changes
    `sections`, `aliases`, `layouts` and `strips`; `render()` and `save()` put them into the TOML text that was read.

    `strips` are those of the layout being edited (`layout`: None for the default one, the top-level strips), so the
    paths of their options are `("strip", 2, "label")` in every layout; `validate()` gives the problems of the edited
    layout these paths too.
    """

    def __init__(self, path: Path, text: str, exists: bool):
        self.path = path
        self.exists = exists
        """Whether the file is there. Without it the document holds the example configuration."""
        self._load(text)

    @classmethod
    def open(cls, path: Path) -> ConfigDocument:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path, example_config(), exists=False)
        except OSError as e:
            raise ConfigError(f"can't read {path}: {e}") from e
        return cls(path, text, exists=True)

    def _load(self, text: str) -> None:
        try:
            toml = tomlkit.parse(text)
        except tomlkit.exceptions.ParseError as e:
            raise ConfigError(f"{self.path} is not valid TOML: {e}") from e
        data = toml.unwrap()
        for name in (*SECTIONS, "aliases"):
            if not isinstance(data.get(name, {}), dict):
                raise ConfigError(f"{self.path}: {name} is not a table ([{name}]), fix that in a text editor first")
        strips = data.pop("strip", [])
        if not _tables(strips):
            raise ConfigError(
                f"{self.path}: strip is not a list of tables ([[strip]]), fix that in a text editor first"
            )
        layouts = data.pop("layout", [])
        if not _tables(layouts) or not all(_tables(layout.get("strip", [])) for layout in layouts):
            raise ConfigError(
                f"{self.path}: layout is not a list of tables with lists of tables ([[layout]], [[layout.strip]]), "
                "fix that in a text editor first"
            )
        self._text = text
        tables: Any = toml.get("strip", [])
        self.sections: dict[str, dict[str, Any] | None] = {
            name: data.pop(name, None if section.optional else {}) for name, section in SECTIONS.items()
        }
        """The options of each section; None for an optional section that is not there."""
        self.aliases: list[tuple[str, str]] = list(data.pop("aliases", {}).items())
        """The aliases in the order of the file; a list, so an alias being typed can have the name of another one."""
        self.default_strips = [
            _draft(strip, origin, table) for origin, (strip, table) in enumerate(zip(strips, tables, strict=True))
        ]
        """The strips of the default layout (the top-level `[[strip]]` list)."""
        layout_tables: Any = toml.get("layout", [])
        self.layouts = [
            LayoutDraft(
                {name: value for name, value in layout.items() if name != "strip"},
                [
                    _draft(strip, origin, strip_table)
                    for origin, (strip, strip_table) in enumerate(
                        zip(layout.get("strip", []), table.get("strip", []), strict=True)
                    )
                ],
                index,
            )
            for index, (layout, table) in enumerate(zip(layouts, layout_tables, strict=True))
        ]
        """The other layouts (`[[layout]]`), in the order of the file."""
        self.layout: int | None = None
        """The layout being edited, an index of `layouts`; None for the default one."""
        self.extra: dict[str, Any] = data
        """Top-level keys that are no section of the configuration: errors, which the user can only remove."""
        self._saved = self.data()
        try:
            self.saved_config: Config | None = Config.model_validate(self._saved)
            """The configuration in the file (the example without one), None when it has errors."""
        except ValidationError:
            self.saved_config = None

    # -- the layouts ----------------------------------------------------------------------------------------------

    @property
    def strips(self) -> list[StripDraft]:
        """The strips of the layout being edited."""
        return self.default_strips if self.layout is None else self.layouts[self.layout].strips

    @property
    def layout_names(self) -> list[str]:
        """The names of every layout, the default one first (as typed, also while they have problems)."""
        return [DEFAULT_LAYOUT, *(layout.name for layout in self.layouts)]

    @property
    def layout_name(self) -> str:
        """The name of the layout being edited."""
        return self.layout_names[0 if self.layout is None else self.layout + 1]

    def edit_layout(self, index: int | None) -> None:
        """Edits the strips of another layout (an index of `layouts`, None for the default one)."""
        if index is not None and not 0 <= index < len(self.layouts):
            raise IndexError(index)
        self.layout = index

    def add_layout(self, copy_strips: bool = False) -> int:
        """
        Adds a layout with a free name (`layout_2`, ...) and edits it: without strips (all `auto`), or with copies of
        the strips of the layout being edited.
        """
        names = set(self.layout_names)
        number = 2
        while f"layout_{number}" in names:
            number += 1
        strips = (
            [StripDraft(copy.deepcopy(strip.values), kept=copy.deepcopy(strip.kept)) for strip in self.strips]
            if copy_strips
            else []
        )
        self.layouts.append(LayoutDraft({"name": f"layout_{number}"}, strips))
        self.layout = len(self.layouts) - 1
        return self.layout

    def remove_layout(self, index: int) -> None:
        """Removes a layout; the default one is edited then."""
        del self.layouts[index]
        self.layout = None

    def move_layout(self, index: int, to: int) -> None:
        """Moves a layout to another place of the order (that of `next`); it stays the one being edited."""
        self.layouts.insert(to, self.layouts.pop(index))
        self.layout = to

    # -- the data -------------------------------------------------------------------------------------------------

    def data(self) -> dict[str, Any]:
        """The configuration as TOML data, as `tomllib` would read the rendered text."""
        data: dict[str, Any] = {
            name: values
            for name, values in self.sections.items()
            # an optional section is there even without options (and then misses the required ones)
            if values is not None and (values or SECTIONS[name].optional)
        }
        if self.aliases:
            data["aliases"] = dict(self.aliases)
        if self.default_strips:
            data["strip"] = [strip.values for strip in self.default_strips]
        if self.layouts:
            data["layout"] = [layout.data() for layout in self.layouts]
        return copy.deepcopy(data | self.extra)

    @property
    def modified(self) -> bool:
        """Whether something changed since the file was read or saved."""
        return self.data() != self._saved

    def strip_changed(self, index: int) -> bool:
        """Whether the strip at `index` (0..7) is not the one of the file there, e.g. edited, added or moved."""
        saved: list[dict[str, Any]] = self._saved.get("strip", [])
        if self.layout is not None:
            layouts: list[dict[str, Any]] = self._saved.get("layout", [])
            saved = layouts[self.layout].get("strip", []) if self.layout < len(layouts) else []
        current = self.strips[index].values if index < len(self.strips) else None
        return current != (saved[index] if index < len(saved) else None)

    @property
    def restart_sections(self) -> tuple[str, ...]:
        """The sections that changed since the file was read or saved and that the daemon takes only with a restart."""
        data = self.data()

        def part(of: dict[str, Any], name: str, option: str | None) -> object:
            section = of.get(name)
            return section.get(option) if option is not None and isinstance(section, dict) else section

        return tuple(
            name
            for name, option in RESTART_SECTIONS.items()
            if part(data, name, option) != part(self._saved, name, option)
        )

    def validate(self) -> Validation:
        problems: list[Problem] = []
        names = Counter(name for name, _ in self.aliases)
        for name, count in names.items():
            if not name:
                problems.append(Problem(("aliases", name), "the name of the application is missing", "missing"))
            elif count > 1:
                problems.append(Problem(("aliases", name), "there are several aliases for it", "duplicate"))
        try:
            config = Config.model_validate(self.data())
        except ValidationError as e:
            problems += [self._edited(problem) for problem in problems_of(e)]
            config = None
        return Validation(None if problems else config, problems)

    def _edited(self, problem: Problem) -> Problem:
        """
        The problem with the path the editor uses: those of the strips of the edited layout start with "strip", its
        own options with "layout", those of the other layouts with "layouts" and the name of the layout.
        """
        match problem.path:
            case ("strip", *rest) if self.layout is not None:
                path: tuple[int | str, ...] = ("layouts", DEFAULT_LAYOUT, "strip", *rest)
            case ("layout", int(index), *rest) if index == self.layout:
                path = tuple(rest) if rest[:1] == ["strip"] else ("layout", *rest)
            case ("layout", int(index), *rest):
                path = ("layouts", self.layout_names[index + 1], *rest)
            case _:
                return problem
        return Problem(path, problem.message, problem.kind)

    def layout_problems(self, validation: Validation, name: str) -> int:
        """How many problems a layout (by its name) and its strips have."""
        if name == self.layout_name:
            return len(validation.at("strip")) + len(validation.at("layout"))
        return len(validation.at("layouts", name))

    # -- editing --------------------------------------------------------------------------------------------------

    def _values(self, path: OptionPath) -> tuple[dict[str, Any], str]:
        match path:
            case (str(section), str(name)) if section in SECTIONS:
                values = self.sections[section]
                if values is None:
                    raise KeyError(f"[{section}] is not there, add it first")
                return values, name
            case ("strip", int(index), str(name)):
                return self.strips[index].values, name
            case ("layout", str(name)) if self.layout is not None:
                return self.layouts[self.layout].values, name
            case (str(name),) if name in self.extra:
                return self.extra, name
        raise KeyError(f"no option at {path}")

    def get(self, path: OptionPath) -> Any:
        """The value of an option in the file, None when it is not set (its default applies)."""
        values, name = self._values(path)
        return values.get(name)

    def set(self, path: OptionPath, value: Any) -> None:
        values, name = self._values(path)
        values[name] = value

    def unset(self, path: OptionPath) -> None:
        """Removes an option from the file, so its default applies (or removes an unknown option)."""
        values, name = self._values(path)
        values.pop(name, None)

    def has_section(self, name: str) -> bool:
        return self.sections[name] is not None

    def add_section(self, name: str) -> None:
        """Adds an optional section (without options yet)."""
        if self.sections[name] is None:
            self.sections[name] = {}

    def remove_section(self, name: str) -> None:
        """Removes an optional section with all its options."""
        assert SECTIONS[name].optional, f"[{name}] is not optional"
        self.sections[name] = None

    def add_strip(self, strip_type: str = "auto") -> int:
        if len(self.strips) >= protocol.STRIPS:
            raise ValueError(f"there are {protocol.STRIPS} strips already")
        self.strips.append(StripDraft({"type": strip_type}))
        return len(self.strips) - 1

    def configure_up_to(self, index: int) -> None:
        """Configures the strips up to `index` (which are `auto` without configuration) as `auto` strips."""
        while len(self.strips) <= index:
            self.add_strip("auto")

    def remove_strip(self, index: int) -> None:
        del self.strips[index]

    def move_strip(self, index: int, to: int) -> None:
        self.strips.insert(to, self.strips.pop(index))

    def set_strip_type(self, index: int, strip_type: str) -> None:
        """
        Changes the type of a strip. The options the new type has too stay, the others are kept for the old type
        (`StripDraft.kept`), and the ones kept for the new type come back. Options the new type has that are kept for
        another type come along as well (and stay kept for it), e.g. the label of an `output` strip that went through
        `apps` and `empty`.
        """
        known = strip_models()[strip_type].model_fields
        strip = self.strips[index]
        old = strip.type if isinstance(strip.type, str) else "unknown"
        options = {name: value for name, value in strip.values.items() if name != "type"}
        left = {name: value for name, value in options.items() if name not in known}
        if left:
            strip.kept[old] = strip.kept.get(old, {}) | left
        others = {
            name: value
            for kind, values in strip.kept.items()
            if kind != strip_type
            for name, value in values.items()
            if name in known
        }
        # what is set now wins over what was kept, e.g. a color set on the way
        shared = {name: value for name, value in options.items() if name in known}
        strip.values = {"type": strip_type} | others | strip.kept.pop(strip_type, {}) | shared

    def state(self) -> DocumentState:
        """A copy of what the editor changes, to go back to with `restore()`."""
        return DocumentState(
            copy.deepcopy(self.sections),
            list(self.aliases),
            copy.deepcopy(self.default_strips),
            copy.deepcopy(self.extra),
            copy.deepcopy(self.layouts),
            self.layout,
        )

    def restore(self, state: DocumentState) -> None:
        state = copy.deepcopy(state)
        self.sections, self.aliases, self.default_strips, self.extra = (
            state.sections,
            state.aliases,
            state.strips,
            state.extra,
        )
        self.layouts, self.layout = state.layouts, state.layout

    # -- the file -------------------------------------------------------------------------------------------------

    def render(self) -> str:
        """The TOML text: the text that was read, with the changes."""
        toml = tomlkit.parse(self._text)
        for name, values in self.sections.items():
            if values is not None:
                toml = _sync_section(toml, name, values)
            elif name in toml:
                del toml[name]
        toml = _sync_section(toml, "aliases", dict(self.aliases))
        _sync_strips(toml, self.default_strips)
        _sync_layouts(toml, self.layouts)
        for name in [name for name in toml if name not in (*ORDER, *self.extra)]:
            del toml[name]
        return tomlkit.dumps(toml)

    def save(self) -> Config:
        """Writes the file, if the configuration has no problems (`ConfigError` otherwise), and returns it."""
        validation = self.validate()
        if validation.config is None:
            problems = "\n".join(f"  {problem}" for problem in validation.problems)
            raise ConfigError(f"{self.path} has errors:\n{problems}")
        text = self.render()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # in place rather than replaced, which keeps a symlink (e.g. into a dotfiles repository) and the permissions
        self.path.write_text(text, encoding="utf-8")
        self.exists = True
        layout = self.layout
        self._load(text)
        # the layouts are still there: the saved file has them
        self.layout = layout
        return validation.config

    def revert(self) -> None:
        """Reads the file again, dropping the changes."""
        layout = self.layout
        if self.exists:
            self._load(self.path.read_text(encoding="utf-8"))
        else:
            self._load(example_config())
        self.layout = layout if layout is not None and layout < len(self.layouts) else None


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


def _sync_section(toml: tomlkit.TOMLDocument, name: str, values: dict[str, Any]) -> tomlkit.TOMLDocument:
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


def _tables(value: object) -> bool:
    """Whether the value is a list of tables."""
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)  # pyright: ignore[reportUnknownVariableType]


def _sync_layouts(toml: tomlkit.TOMLDocument, layouts: list[LayoutDraft]) -> None:
    """Like `_sync_strips`: the layouts that stay where they were keep their tables, comments and formatting."""
    tables: Any = toml.get("layout", [])
    if [layout.origin for layout in layouts] == list(range(len(tables))):
        for layout, table in zip(layouts, tables, strict=True):
            _sync_items(table, layout.values, keep=("strip",))
            _sync_strips(table, layout.strips)
        return
    aot = tomlkit.aot()
    for layout in layouts:
        table = copy.deepcopy(tables[layout.origin]) if layout.origin is not None else tomlkit.table()
        _sync_items(table, layout.values, keep=("strip",))
        _sync_strips(table, layout.strips)
        aot.append(table)
    if not layouts:
        del toml["layout"]
    elif "layout" in toml:
        toml["layout"] = aot
    else:
        toml.append("layout", aot)


def _sync_strips(toml: tomlkit.TOMLDocument | Table, strips: list[StripDraft]) -> None:
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
    trailing = [item for item in _trim(table) if not isinstance(item, Null)]
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


def _draft(values: dict[str, Any], origin: int, table: Table) -> StripDraft:
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
    """Takes the comments and blank lines at the end of the table out of it, and returns them."""
    body = table.body if isinstance(table, Container) else table.value.body
    trailing: list[Any] = []
    # keyless items at the end are in no index of the table, taking them out leaves it intact
    while body and body[-1][0] is None:
        trailing.insert(0, body.pop()[1])
    return trailing
