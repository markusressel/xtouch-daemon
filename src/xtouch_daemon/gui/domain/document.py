"""
A configuration file being edited: its options as plain data the editor changes, validated with the pydantic models
of the configuration, and written back into the original TOML text, so comments and formatting of the user stay
where they can.
"""

import copy
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
import tomlkit.exceptions
from pydantic import ValidationError
from tomlkit.container import Container
from tomlkit.items import Table, Whitespace

from xtouch_daemon import protocol
from xtouch_daemon.config import Config, ConfigError, Problem, example_config, problems_of
from xtouch_daemon.gui.domain.schema import Section, sections, strip_models

SECTIONS: dict[str, Section] = {section.name: section for section in sections()}
"""The sections with options of their own (`[device]`, `[behavior]`, `[mqtt]`), edited option by option."""

RESTART_SECTIONS = ("device", "mqtt")
"""What a reload does not change: the daemon keeps the device it opened, and its configuration on a new `[mqtt]`."""

ORDER = (
    *(name for name, section in SECTIONS.items() if not section.optional),
    "aliases",
    "strip",
    *(name for name, section in SECTIONS.items() if section.optional),
)
"""Where a new section goes in the file: optional ones like `[mqtt]` at the end, like in the example."""

type OptionPath = tuple[int | str, ...]
"""Where an option is in the TOML data, like `Problem.path`, e.g. `("strip", 2, "label")`."""


@dataclass
class StripDraft:
    """A strip being edited: its options as in the file."""

    values: dict[str, Any]
    origin: int | None = None
    """Its position in the file when it was read, which keeps its comments and formatting when it moves."""

    @property
    def type(self) -> str | None:
        return self.values.get("type")


@dataclass(frozen=True)
class DocumentState:
    """Everything the editor changes in a document, for undo (see `ConfigDocument.state()`)."""

    sections: dict[str, dict[str, Any] | None]
    aliases: list[tuple[str, str]]
    strips: list[StripDraft]
    extra: dict[str, Any]

    def data(self) -> dict[str, Any]:
        """What the configuration is in this state, as `ConfigDocument.data()` (to compare states)."""
        return {"sections": self.sections, "aliases": self.aliases, "strips": [strip.values for strip in self.strips]}


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
    `sections`, `aliases` and `strips`; `render()` and `save()` put them into the TOML text that was read.
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
        if not isinstance(strips, list) or not all(isinstance(strip, dict) for strip in strips):
            raise ConfigError(
                f"{self.path}: strip is not a list of tables ([[strip]]), fix that in a text editor first"
            )
        self._text = text
        self.sections: dict[str, dict[str, Any] | None] = {
            name: data.pop(name, None if section.optional else {}) for name, section in SECTIONS.items()
        }
        """The options of each section; None for an optional section that is not there."""
        self.aliases: list[tuple[str, str]] = list(data.pop("aliases", {}).items())
        """The aliases in the order of the file; a list, so an alias being typed can have the name of another one."""
        self.strips = [StripDraft(strip, origin) for origin, strip in enumerate(strips)]
        self.extra: dict[str, Any] = data
        """Top-level keys that are no section of the configuration: errors, which the user can only remove."""
        self._saved = self.data()
        try:
            self.saved_config: Config | None = Config.model_validate(self._saved)
            """The configuration in the file (the example without one), None when it has errors."""
        except ValidationError:
            self.saved_config = None

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
        if self.strips:
            data["strip"] = [strip.values for strip in self.strips]
        return copy.deepcopy(data | self.extra)

    @property
    def modified(self) -> bool:
        """Whether something changed since the file was read or saved."""
        return self.data() != self._saved

    def strip_changed(self, index: int) -> bool:
        """Whether the strip at `index` (0..7) is not the one of the file there, e.g. edited, added or moved."""
        saved: list[dict[str, Any]] = self._saved.get("strip", [])
        current = self.strips[index].values if index < len(self.strips) else None
        return current != (saved[index] if index < len(saved) else None)

    @property
    def restart_sections(self) -> tuple[str, ...]:
        """The sections that changed since the file was read or saved and that the daemon takes only with a restart."""
        data = self.data()
        return tuple(name for name in RESTART_SECTIONS if data.get(name) != self._saved.get(name))

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
            problems += problems_of(e)
            config = None
        return Validation(None if problems else config, problems)

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
        """Changes the type of a strip; the options the new type has too are kept."""
        known = strip_models()[strip_type].model_fields
        strip = self.strips[index]
        strip.values = {"type": strip_type} | {
            name: value for name, value in strip.values.items() if name in known and name != "type"
        }

    def state(self) -> DocumentState:
        """A copy of what the editor changes, to go back to with `restore()`."""
        return DocumentState(
            copy.deepcopy(self.sections), list(self.aliases), copy.deepcopy(self.strips), copy.deepcopy(self.extra)
        )

    def restore(self, state: DocumentState) -> None:
        state = copy.deepcopy(state)
        self.sections, self.aliases, self.strips, self.extra = state.sections, state.aliases, state.strips, state.extra

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
        _sync_strips(toml, self.strips)
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
        self._load(text)
        return validation.config

    def revert(self) -> None:
        """Reads the file again, dropping the changes."""
        if self.exists:
            self._load(self.path.read_text(encoding="utf-8"))
        else:
            self._load(example_config())


def _sync_items(table: Container | Table, values: dict[str, Any]) -> None:
    """Makes the options of the table the values, leaving the ones that did not change (and their comments) alone."""
    for name in [name for name in table if name not in values]:
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
            table[name] = value
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


def _sync_strips(toml: tomlkit.TOMLDocument, strips: list[StripDraft]) -> None:
    tables: Any = toml.get("strip", [])
    if [strip.origin for strip in strips] == list(range(len(tables))):
        for strip, table in zip(strips, tables, strict=True):
            _sync_items(table, strip.values)
        return
    aot = tomlkit.aot()
    for strip in strips:
        table = copy.deepcopy(tables[strip.origin]) if strip.origin is not None else tomlkit.table()
        _sync_items(table, strip.values)
        # the blank lines after it were for its old place, the array of tables puts one between its tables
        for item in _trim(table):
            if not isinstance(item, Whitespace):
                table.add(item)
        aot.append(table)
    if not strips:
        del toml["strip"]
    elif "strip" in toml:
        toml["strip"] = aot
    else:
        toml.append("strip", aot)


def _trim(table: Container | Table) -> list[Any]:
    """Takes the comments and blank lines at the end of the table out of it, and returns them."""
    body = table.body if isinstance(table, Container) else table.value.body
    trailing: list[Any] = []
    # keyless items at the end are in no index of the table, taking them out leaves it intact
    while body and body[-1][0] is None:
        trailing.insert(0, body.pop()[1])
    return trailing
