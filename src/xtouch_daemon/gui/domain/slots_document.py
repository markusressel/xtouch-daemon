"""
A configuration file of channels, states and slots being edited: the whole file as plain data that the editor
changes by option paths (`("channel", "mic", "label")`, `("slots", "3")`, `("state", "call", "delay_off")`), validated
with `parse_config()`, and written back into the original TOML text, so comments, the order of the file and the form
of each value (a stack as a string, a list or tables) stay where they did not change.
"""

import copy
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeIs

import tomlkit
import tomlkit.exceptions
from tomlkit.container import Container
from tomlkit.items import AoT, InlineTable, Table

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import Problem, example_config, parse_config
from xtouch_daemon.config.model import Config
from xtouch_daemon.gui.domain.schema import RESTART_SECTIONS, SECTIONS

type OptionPath = tuple[str | int, ...]
"""Where an option is in the data of the file, e.g. `("channel", "mic", "label")` or `("slots", "3", 0)`."""

_WHERE = re.compile(r"^(?P<where>[A-Za-z0-9_.\[\]-]+)(?: \([^)]*\))?: (?P<message>.*)$")
"""A line of the errors of a file: `slots.3[0] (radio): ...` is about `slots.3[0]`."""
_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_OPTION = re.compile(r"^(?P<option>[a-z_]+(?:\.[a-z0-9_]+)*): (?P<message>.*)$")
"""An option in a problem of a channel or candidate: `profiles.1.label: ...`."""


def path_of(where: str) -> OptionPath:
    """The option path of a place in an error message: `slots.1[0]` is `("slots", "1", 0)`."""
    return tuple(int(index) if index else name for name, index in _PART.findall(where))


def problems_of(error: ConfigError) -> list[Problem]:
    """The problems of a file that `parse_config()` refused, each with the path of its option."""
    lines = str(error).splitlines()
    details = [line.strip() for line in lines[1:]] if lines[0].endswith("has errors:") else [str(error)]
    problems: list[Problem] = []
    for line in details:
        match = _WHERE.match(line)
        if match is None:
            problems.append(Problem((), line, "invalid"))
        else:
            path = path_of(match["where"])
            message = match["message"].removeprefix("Value error, ")
            # the problem of an option of a channel or candidate: `channel.out: profiles.1.label: Field required`
            option = _OPTION.match(message)
            if option is not None:
                path = (*path, *(int(part) if part.isdigit() else part for part in option["option"].split(".")))
                message = option["message"]
            kind = "extra_forbidden" if message == "Extra inputs are not permitted" else "invalid"
            problems.append(Problem(path, message, kind))
    return problems


@dataclass(frozen=True)
class Validation:
    config: Config | None
    """The configuration, None while it has problems."""
    problems: list[Problem] = field(default_factory=list[Problem])

    def at(self, *path: str | int) -> list[Problem]:
        """The problems of an option, or of a section, channel, state or slot and everything in it."""
        return [problem for problem in self.problems if problem.path[: len(path)] == path]


@dataclass(frozen=True)
class Snapshot:
    """The data of a document at one moment, for undo."""

    values: dict[str, Any]

    def data(self) -> dict[str, Any]:
        return self.values


class SlotsDocument:
    """The configuration file at `path`, or the example configuration while there is no file yet."""

    def __init__(self, path: Path, text: str, exists: bool):
        self.path = path
        self.exists = exists
        """Whether the file is there. Without it the document holds the example configuration."""
        self._load(text)

    @classmethod
    def open(cls, path: Path) -> SlotsDocument:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path, example_config(), exists=False)
        except OSError as e:
            raise ConfigError(f"can't read {path}: {e}") from e
        return cls(path, text, exists=True)

    def _load(self, text: str) -> None:
        try:
            # the errors of tomllib say where
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{self.path} is not valid TOML: {e}") from e
        self._toml = tomlkit.parse(text)
        self._text = text
        self.values: dict[str, Any] = self._toml.unwrap()
        """The file as plain data, which the editor changes."""
        self._saved = copy.deepcopy(self.values)
        self.saved_config = self._config(text) if self.exists else None
        """The configuration of the file as it is on disk, None while there is none the daemon would take."""

    # -- options ----------------------------------------------------------------------------------------------------

    def get(self, path: OptionPath, default: Any = None) -> Any:
        """The value at `path`, `default` without one."""
        value: Any = self.values
        for key in path:
            try:
                value = value[key]
            except KeyError, IndexError, TypeError:
                return default
        return value

    def set(self, path: OptionPath, value: Any) -> None:
        """Sets the value at `path`, with the tables on the way."""
        parent = self._parent(path, create=True)
        parent[path[-1]] = copy.deepcopy(value)

    def unset(self, path: OptionPath) -> None:
        """Removes the value at `path`, and the tables on the way that end up empty."""
        parent = self._parent(path, create=False)
        if parent is None:
            return
        key = path[-1]
        if isinstance(parent, list):
            if isinstance(key, int) and key < len(parent):
                del parent[key]
        else:
            parent.pop(key, None)
        # a section with options of its own stays (an optional one like [mqtt] is there or not, see
        # `remove_section()`), and so does a state without options (on only by an override, or one being set up:
        # Add makes one empty); an emptied channel or [state] goes
        named_state = len(path) == 3 and path[0] == "state"
        if len(path) > 1 and not parent and not named_state and (len(path) > 2 or path[0] not in SECTIONS):
            self.unset(path[:-1])

    def rename(self, path: OptionPath, new: str) -> None:
        """Gives the table at `path` (a channel, a state, ...) another key, in its place among the others."""
        parent = self._parent(path, create=False)
        assert isinstance(parent, dict), f"nothing at {path}"
        assert path[-1] in parent, f"nothing at {path}"
        # in the TOML too, so the table keeps its comments and form
        _sync(self._toml, self.values, 0)
        container: Any = self._toml
        for key in path[:-1]:
            container = container[key]
        items = [(key, container[key]) for key in list(container)]
        for key, _ in items:
            del container[key]
        for key, item in items:
            container[new if key == path[-1] else key] = item
        renamed = {new if key == path[-1] else key: value for key, value in parent.items()}
        parent.clear()
        parent.update(renamed)

    def has_section(self, name: str) -> bool:
        return name in self.values

    def add_section(self, name: str) -> None:
        """Adds a section (without options yet), e.g. `[mqtt]`."""
        self.values.setdefault(name, {})

    def remove_section(self, name: str) -> None:
        """Removes a section with all its options."""
        self.values.pop(name, None)

    def _parent(self, path: OptionPath, create: bool) -> Any:
        assert path, "an option path names an option"
        parent: Any = self.values
        for key in path[:-1]:
            if isinstance(parent, dict) and key not in parent:
                if not create:
                    return None
                parent[key] = {}
            parent = parent[key]
        return parent

    # -- the file ---------------------------------------------------------------------------------------------------

    @property
    def modified(self) -> bool:
        """Whether the data differs from the file."""
        return self.values != self._saved

    def validate(self) -> Validation:
        try:
            return Validation(parse_config(self.render(), str(self.path)))
        except ConfigError as e:
            return Validation(None, problems_of(e))

    @property
    def restart_sections(self) -> tuple[str, ...]:
        """The sections that changed since the file was read or saved and that the daemon takes only with a restart."""
        saved = self._saved

        def part(data: dict[str, Any], name: str, option: str | None) -> object:
            section = data.get(name)
            return section.get(option) if option is not None and isinstance(section, dict) else section

        return tuple(
            name
            for name, option in RESTART_SECTIONS.items()
            if part(self.values, name, option) != part(saved, name, option)
        )

    def _config(self, text: str) -> Config | None:
        try:
            return parse_config(text, str(self.path))
        except ConfigError:
            return None

    def render(self) -> str:
        """The TOML text of the data: the text that was read, with the changes."""
        _sync(self._toml, self.values, 0)
        return tomlkit.dumps(self._toml)

    def save(self) -> Config:
        """Writes the file; ConfigError (and nothing written) while it has problems."""
        text = self.render()
        config = parse_config(text, str(self.path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")
        self.exists = True
        self._saved = copy.deepcopy(self.values)
        self.saved_config = config
        return config

    def revert(self) -> None:
        """Back to the file as it is on disk (or the example)."""
        fresh = SlotsDocument.open(self.path)
        self.__dict__.update(fresh.__dict__)

    def state(self) -> Snapshot:
        return Snapshot(copy.deepcopy(self.values))

    def restore(self, state: Snapshot) -> None:
        self.values = copy.deepcopy(state.values)


INLINE_SECTIONS = frozenset({"controls"})
"""Sections whose entries are inline tables when they are new (`2 = { select = "toggle:call" }`)."""


def _sync(container: Container | Table | InlineTable, values: dict[str, Any], depth: int, section: str = "") -> None:
    """
    Makes the items of `container` the values: what did not change stays as it is (comments, the form of a stack),
    a changed table or array of tables is synced item by item, anything else is written anew. New tables are
    sections (`[channel.mic]`) in the sections of the file, inline tables below them and in `[controls]`.
    """
    current = container.unwrap()
    for key in [key for key in current if key not in values]:
        del container[key]
    for key, value in values.items():
        if key in current and current[key] == value:
            continue
        here = section or key
        existing = container.get(key) if key in current else None
        if isinstance(value, dict) and isinstance(existing, Table | InlineTable):
            _sync(existing, value, depth + 1, here)
        elif isinstance(existing, AoT) and _tables(value):
            _sync_aot(existing, value, depth + 1, here)
        elif isinstance(value, dict):
            inline = isinstance(existing, InlineTable) or depth >= 2 or (depth == 1 and section in INLINE_SECTIONS)
            container[key] = _table(value, depth + 1, inline, here)
        else:
            container[key] = _item(value)


def _tables(value: Any) -> TypeIs[list[dict[str, Any]]]:
    return isinstance(value, list) and bool(value) and all(isinstance(each, dict) for each in value)


def _sync_aot(aot: AoT, values: list[dict[str, Any]], depth: int, section: str) -> None:
    """An array of tables (`[[channel.out.choices]]`) stays one: its tables are synced, added or removed."""
    while len(aot) > len(values):
        del aot[len(aot) - 1]
    for index, value in enumerate(values):
        if index < len(aot):
            _sync(aot[index], value, depth, section)
        else:
            aot.append(_table(value, depth, False, section))


def _table(values: dict[str, Any], depth: int, inline: bool, section: str) -> Table | InlineTable:
    if inline:
        table: Table | InlineTable = tomlkit.inline_table()
        for key, value in values.items():
            table[key] = _item(value)
        return table
    table = tomlkit.table(is_super_table=bool(values) and all(isinstance(value, dict) for value in values.values()))
    _sync(table, values, depth, section)
    return table


def _item(value: Any) -> Any:
    """A value for a key: tables in lists and in values are inline (a candidate with options)."""
    if isinstance(value, dict):
        return _table(value, 2, True, "")
    if isinstance(value, list):
        array = tomlkit.array()
        array.extend(_item(each) for each in value)
        return array
    return value
