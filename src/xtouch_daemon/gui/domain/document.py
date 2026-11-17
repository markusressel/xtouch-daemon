"""
A configuration file being edited: its options as plain data the editor changes, validated with the pydantic models
of the configuration, and written back into the original TOML text, so comments and formatting of the user stay
where they can.
"""

import copy
from collections import Counter
from pathlib import Path
from typing import Any

import tomlkit
import tomlkit.exceptions
from pydantic import ValidationError

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import Problem, example_config, problems_of
from xtouch_daemon.config.legacy.model import LegacyConfig as Config
from xtouch_daemon.config.values import DEFAULT_LAYOUT
from xtouch_daemon.gui.domain.clipboard import CopiedStrip, Paste
from xtouch_daemon.gui.domain.drafts import (
    RESTART_SECTIONS,
    SECTIONS,
    DocumentState,
    LayoutDraft,
    OptionPath,
    StripDraft,
    Validation,
)
from xtouch_daemon.gui.domain.flow import why_not_add
from xtouch_daemon.gui.domain.schema import strip_models
from xtouch_daemon.gui.domain.toml_sync import ORDER, are_tables, draft_of, sync_layouts, sync_section, sync_strips


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
        if not are_tables(strips):
            raise ConfigError(
                f"{self.path}: strip is not a list of tables ([[strip]]), fix that in a text editor first"
            )
        layouts = data.pop("layout", [])
        if not are_tables(layouts) or not all(are_tables(layout.get("strip", [])) for layout in layouts):
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
            draft_of(strip, origin, table) for origin, (strip, table) in enumerate(zip(strips, tables, strict=True))
        ]
        """The strips of the default layout (the top-level `[[strip]]` list)."""
        layout_tables: Any = toml.get("layout", [])
        self.layouts = [
            LayoutDraft(
                {name: value for name, value in layout.items() if name != "strip"},
                [
                    draft_of(strip, origin, strip_table)
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
        """
        Adds a strip at the end. Beyond the 8 of the device only while it could get a place (see `flow.why_not_add()`):
        ValueError says why not.
        """
        reason = why_not_add([strip.values for strip in self.strips])
        if reason is not None:
            raise ValueError(reason)
        self.strips.append(StripDraft({"type": strip_type}))
        return len(self.strips) - 1

    def configure_up_to(self, index: int) -> None:
        """Configures the strips up to `index` (which are `auto` without configuration) as `auto` strips."""
        while len(self.strips) <= index:
            self.add_strip("auto")

    def remove_strip(self, index: int) -> None:
        """
        Removes a strip from its place, which becomes an `auto` strip (what a place without a strip is): the strips
        after it stay where they are. The last one goes, and so do `auto` strips without options it leaves at the end.
        """
        if index < len(self.strips) - 1:
            self.strips[index] = StripDraft({"type": "auto"})
            return
        del self.strips[index]
        self._trim()

    def move_strip(self, index: int, to: int) -> None:
        """Moves a strip to another place, also to one after the last strip: the places in between are `auto` strips."""
        while len(self.strips) <= to:
            self.strips.append(StripDraft({"type": "auto"}))
        self.strips.insert(to, self.strips.pop(index))
        self._trim()

    def copy_strip(self, index: int) -> CopiedStrip:
        """The strip at `index` of the layout being edited, to paste elsewhere (see `paste_strip()`)."""
        return CopiedStrip.of(self.layout_name, index, self.strips[index])

    def paste_strip(self, index: int, copied: CopiedStrip, paste: Paste) -> None:
        """
        Puts a copied strip at `index` instead of the strip there, also after the last strip: the places in between
        are `auto` strips.
        """
        self.configure_up_to(index)
        self.strips[index] = copied.draft(paste)
        self._trim()

    def _trim(self) -> None:
        """Drops the `auto` strips without options at the end: a place without a strip is one."""
        while self.strips and self.strips[-1].values == {"type": "auto"} and not self.strips[-1].kept:
            self.strips.pop()

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
                toml = sync_section(toml, name, values)
            elif name in toml:
                del toml[name]
        toml = sync_section(toml, "aliases", dict(self.aliases))
        sync_strips(toml, self.default_strips)
        sync_layouts(toml, self.layouts)
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
