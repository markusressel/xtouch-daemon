"""
A form: the rows of the options of one place of the document (a section, a channel, a pool, a state), made from the
models. The form reads the values from the document, puts what a field edits back through the `Editor` (typing in one
option is one step to undo), and says per row what to show: the value, the placeholder, the meaning, the problems.
QML shows it (`FormView` of `XTouch.Forms`): a row per option, its field by the kind of the option.

A form keeps its rows (`FormRowsModel`) by the names of the options. A new value changes the `state` of its row in
place; the rows, the fields and their columns are not made anew. Loading values never writes them back.

For a page: `Form(forms_of(app), [RowSpec(option), ...], base=("behavior",))`, or the rows of a strip type with
`strip_rows`. A form for another place of the document (another channel of the same type) is `form.retarget(base)`.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QFontMetricsF, QGuiApplication

from xtouch_daemon.config.files import Problem
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.demos import Part, Strip, scene
from xtouch_daemon.gui.domain.entities import attribute_suggestions
from xtouch_daemon.gui.domain.schema import Kind, Option, describe
from xtouch_daemon.gui.domain.slots_document import OptionPath
from xtouch_daemon.gui.domain.sources import Suggestion, preset_suggestions, preset_tip
from xtouch_daemon.gui.qt.preview.part_view import CAPTION_WIDTH
from xtouch_daemon.gui.quick.device.part import PartPreviewModel
from xtouch_daemon.gui.quick.forms import binding, entity_table, suggestions, tables
from xtouch_daemon.gui.quick.forms.buttons import ButtonLogic
from xtouch_daemon.gui.quick.forms.context import FormContext
from xtouch_daemon.gui.quick.forms.help import colors_of
from xtouch_daemon.gui.quick.forms.model import FormRowsModel, plain, spec_of
from xtouch_daemon.gui.quick.forms.suggestions import NO_SUGGESTIONS, NO_SUGGESTIONS_OF, Suggest, TableSuggest

LABEL_WIDTH = 144
"""The width of the column of names of a form."""
WIDEST_TITLE = LABEL_WIDTH + 2 * 16
"""The widest column of names `title_width` makes: a longer name wraps."""
MATCHED = frozenset({"device", "card", "profile"})
"""The options whose value names something of the sound server, with what it matches under the field."""
TALL = (Kind.TABLES, Kind.BUTTON, Kind.CLAIM, Kind.BINDING)
"""The kinds that are a list of entries: their name and reset button are at the top, not beside the middle."""


@dataclass
class RowSpec:
    """One row of a form: its option, and where the option is and what it suggests, beyond what the model says."""

    option: Option
    path: OptionPath | None = None
    """Where the option is in the document, by default the base of the form and its name."""
    suggest: Suggest | TableSuggest | None = None
    """What a text, a list or the columns of a table suggest."""
    placeholder: Callable[[], str] | None = None
    """What an unset option takes where that is no plain default, e.g. `none: the fader stays down`."""
    link: str | None = None
    """The page of the documentation "Learn more" opens."""
    names: tuple[str, ...] = ()
    """The options of the document the row edits (their problems are the row's), by default its own."""
    inherited: str | None = None
    """Where an unset value comes from when it is no default, e.g. "As on the channel" at a place."""
    resettable: bool = True
    group: str = ""
    """The heading the row stands under, e.g. "Buttons"; rows with the same one are together."""
    get: Callable[[], Any] | None = None
    """Reads the value, for a row that is not one option (the devices, the meter); None: unset."""
    put: Callable[[Any], None] | None = None
    """Writes the value (None: unsets), for such a row."""
    buttons: ButtonLogic | None = None
    channels: Callable[[], list[str]] = list
    """The `custom` channels a part of `[controls]` can set."""
    nothing: str | None = None
    """What the suggestions say without any."""
    preview: str = ""
    """The part of the strip (`encoder`, `display`, `buttons`, `fader`) a preview of this row's group shows."""
    title: str = ""
    """The name of the row where it is not the option's, e.g. "LCD line" for `lcd` in `[controls]`."""
    reset_tip: str = ""
    """What the reset button says, where "Back to the default" is not what it does."""

    @property
    def name(self) -> str:
        return self.option.name


def unset_text(inherited: str | None, value: object, before: str = "default: ") -> str:
    """What a field shows while unset: `default: <value>`, or where it comes from with its value."""
    if inherited is None:
        return "" if value is None else f"{before}{value}"
    return f"{inherited}: {value}" if value else inherited


class Form(QObject):
    """See the module."""

    changed = pyqtSignal(arguments=[])
    """The rows were shown again after a change of the document."""
    restChanged = pyqtSignal(arguments=[])
    titleWidthChanged = pyqtSignal(arguments=[])
    activeChanged = pyqtSignal(arguments=[])
    edited = pyqtSignal(str, arguments=["name"])
    """A field of the row `name` changed the document."""

    def __init__(
        self,
        context: FormContext,
        specs: Sequence[RowSpec] = (),
        base: OptionPath = (),
        present: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or context)  # pyright: ignore[reportArgumentType]
        self.context = context
        self.editor = context.editor
        self.base = base
        self.present = present
        """Whether the place is in the document; rows read nothing (they show defaults) while it is not."""
        self._model = FormRowsModel(self)
        self._specs: dict[str, RowSpec] = {}
        self._rest: list[str] = []
        self._resolved: dict[str, Any] = {}
        self.strip = ""
        """The strip type the form is for (what the previews of its groups show)."""
        self._previews: dict[str, PartPreviewModel] = {}
        self._title_width = 0
        self._active = True
        self._dirty = False
        self.least = 0
        """The longest name of rows shown with this form's, so the column of names is as wide as theirs."""
        self.editor.changed.connect(self._changed)
        context.audioChanged.connect(self._audio_changed)
        context.entitiesChanged.connect(self._audio_changed)
        self.set_specs(specs)

    # -- what QML reads ---------------------------------------------------------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def rows(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._model

    @pyqtProperty(QObject, constant=True)
    def tools(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The helpers every form shares (`FormContext`): the help as rich text, the file dialog, lists of tables."""
        return self.context

    @pyqtProperty("QStringList", notify=restChanged)
    def rest(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        """The problems of the place that belong to no row (the whole section, an unknown option)."""
        return self._rest

    @pyqtProperty(int, notify=titleWidthChanged)
    def titleWidth(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The width of the column of names: the longest name of the rows shown, up to `WIDEST_TITLE`."""
        return self._title_width

    resolvedChanged = pyqtSignal(arguments=[])

    @pyqtProperty("QVariantMap", notify=resolvedChanged)
    def resolved(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """The value of every option as it counts (unset ones as their defaults): what a preview of a part shows."""
        return self._resolved

    @pyqtProperty(str, constant=True)
    def stripType(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self.strip

    @pyqtProperty(int, constant=True)
    def previewWidth(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The width of the preview of a part, in pixels at 100 %: the options of its group make room for it."""
        return CAPTION_WIDTH

    @pyqtProperty(bool, notify=activeChanged)
    def active(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._active

    @active.setter
    def active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.activeChanged.emit()
            if active and self._dirty:
                self.refresh()

    @pyqtProperty("QStringList", constant=True)
    def basePath(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return [str(each) for each in self.base]

    # -- the rows ---------------------------------------------------------------------------------------------------

    def set_specs(self, specs: Sequence[RowSpec]) -> None:
        """The rows of the form (by the names of their options); the ones that stay change in place."""
        self._specs = {spec.name: spec for spec in specs}
        self._statics = {spec.name: self._static(spec) for spec in specs}
        group = ""
        for index, spec in enumerate(specs):
            static = self._statics[spec.name]
            # a heading where a group starts, a line between the rows of a group (a row shown with another sits
            # under it)
            static["groupStart"] = spec.group != group
            static["divided"] = index > 0 and spec.group == group and spec.option.shown_with is None
            group = spec.group
        # the last row of its group
        for index, spec in enumerate(specs):
            after = specs[index + 1] if index + 1 < len(specs) else None
            self._statics[spec.name]["groupEnd"] = after is None or after.group != spec.group
        self.refresh()

    def retarget(self, base: OptionPath) -> None:
        """The same rows for another place of the document (another channel of the type); the values are its own."""
        self.base = base
        self.refresh()

    def path_of(self, spec: RowSpec, name: str | None = None) -> OptionPath:
        return spec.path if spec.path is not None and name is None else (*self.base, name or spec.name)

    def _static(self, spec: RowSpec) -> dict[str, Any]:
        option = spec.option
        static = spec_of(option)
        static.update(
            {
                "titleText": (spec.title or option.title) + ("  *" if option.required else ""),
                "titleTip": option.name + (", required" if option.required else ""),
                "tall": option.kind in TALL,
                "link": spec.link or "",
                "group": spec.group,
                "preview": spec.preview,
                "suggests": spec.suggest is not None or option.presets is not None,
                "suggestColumns": sorted(spec.suggest) if isinstance(spec.suggest, Mapping) else [],
                "matched": option.name in MATCHED and callable(spec.suggest),
                "modes": binding.modes_of(option) if option.kind == Kind.BINDING else [],
                "columnPlaceholders": self._column_placeholders(option),
                "nothing": spec.nothing or NO_SUGGESTIONS_OF.get(option.name, NO_SUGGESTIONS),
            }
        )
        return static

    @staticmethod
    def _column_placeholders(option: Option) -> dict[str, str]:
        if option.kind == Kind.BINDING:
            return {
                name: text
                for name, text in binding.COLUMN_PLACEHOLDERS.items()
                if any(column.name == name and not column.required for column in option.columns)
            }
        return dict(tables.TABLE_PLACEHOLDERS) if option.kind == Kind.TABLES else {}

    def _read(self, spec: RowSpec) -> Any:
        if spec.get is not None:
            return spec.get()
        if self.present is not None and not self.present():
            return None
        return self.editor.document.get(self.path_of(spec))

    def _values(self) -> dict[str, Any]:
        """The values of the options by name, an unset one as its default (see `Option.shown`)."""
        values: dict[str, Any] = {}
        for name, spec in self._specs.items():
            value = self._read(spec)
            values[name] = spec.option.default if value is None else value
        return values

    def refresh(self) -> None:
        """Shows the document again: the rows keep their fields, their states change in place."""
        if not self._active:
            self._dirty = True
            return
        self._dirty = False
        values = self._values()
        validation = self.editor.validation
        rows: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
        claimed: set[tuple[Any, ...]] = set()
        for name, spec in self._specs.items():
            problems: list[Problem] = []
            for each in spec.names or (name,):
                path = self.path_of(spec, each)
                claimed.add(path)
                problems.extend(validation.at(*path))
            rows.append((name, self._statics[name], self._state(spec, values, problems)))
        self._model.show(rows)
        resolved = plain(values)
        if resolved != self._resolved:
            self._resolved = resolved
            self.resolvedChanged.emit()
        self._show_rest(claimed, validation)
        self._show_title_width()
        self._play_previews()
        self.changed.emit()

    @pyqtSlot(str, result=QObject)  # pyright: ignore[reportArgumentType]
    def previewModel(self, part: str) -> QObject:
        """The model of the preview of a part (`encoder`, `display`, ...): it plays what the values do."""
        if not part:
            # a preview that is not told its part yet: one of its own, so it takes no hook of a later one
            return PartPreviewModel("display", self)
        found = self._previews.get(part)
        if found is None:
            found = self._previews[part] = PartPreviewModel(cast(Part, part), self)
            self._play(part, found)
        return found

    def _play_previews(self) -> None:
        for part, model in self._previews.items():
            self._play(part, model)

    def _play(self, part: str, model: PartPreviewModel) -> None:
        config = self.editor.validation.config
        behavior = config.behavior if config else BehaviorConfig()
        model.play(scene(cast(Part, part), Strip(self.strip, self._resolved, behavior)))

    def _show_rest(self, claimed: set[tuple[Any, ...]], validation: Any) -> None:
        """The problems of the place that no row shows: its whole (`[device]`) or an option the model doesn't know."""
        if not self.base:
            rest: list[str] = []
        else:
            rest = [
                problem.message if len(problem.path) == len(self.base) else str(problem)
                for problem in validation.at(*self.base)
                if not any(problem.path[: len(path)] == path for path in claimed)
            ]
        if rest != self._rest:
            self._rest = rest
            self.restChanged.emit()

    def _show_title_width(self) -> None:
        metrics = QFontMetricsF(QGuiApplication.font())
        width = max(
            (int(metrics.horizontalAdvance(static["titleText"])) + 2 for static in self._statics.values()),
            default=0,
        )
        width = max(min(WIDEST_TITLE, width), min(WIDEST_TITLE, self.least))
        if width != self._title_width:
            self._title_width = width
            self.titleWidthChanged.emit()

    def _changed(self, change: Change) -> None:
        if change.scope is not Scope.FILE:
            self.refresh()

    def _audio_changed(self) -> None:
        self.refresh()

    # -- what a row shows -------------------------------------------------------------------------------------------

    def _state(self, spec: RowSpec, values: Mapping[str, Any], problems: list[Problem]) -> dict[str, Any]:
        option = spec.option
        value = self._read(spec)
        shown = option.default if value is None else value
        kind = option.kind
        text, nested = self._problems(spec, problems)
        state: dict[str, Any] = {
            "value": plain(value),
            "shown": plain(self._shown(spec, kind, value, shown)),
            "set": value is not None,
            "placeholder": self._placeholder(spec, value),
            "problems": text,
            "nested": nested,
            "visible": option.shown(values),
            "resettable": spec.resettable and value is not None and not option.required,
            "resetTip": spec.reset_tip or f"Back to the default ({describe(option.default)})",
            "meaning": self._meaning(spec, value),
            "matches": self._matches(spec, value),
            "helpDefault": option.default_text or (self._default_help(spec)),
            "inherited": spec.inherited or "",
        }
        if kind == Kind.BINDING:
            state.update(self._binding_state(spec, value))
        return state

    def _shown(self, spec: RowSpec, kind: Kind, value: Any, shown: Any) -> Any:
        option = spec.option
        if kind in (Kind.INTEGER, Kind.NUMBER):
            return shown if isinstance(shown, int | float) and not isinstance(shown, bool) else option.default
        if kind == Kind.SWITCH:
            if value is None and spec.inherited is not None and spec.placeholder:
                return spec.placeholder() == "on"
            return bool(shown)
        if kind == Kind.COLOR:
            if value is None and spec.inherited is not None and spec.placeholder:
                return spec.placeholder()
            return str(shown)
        if kind == Kind.LIST:
            return [shown] if isinstance(shown, str) else [str(item) for item in shown or ()]
        if kind == Kind.NUMBERS:
            return list(shown) if isinstance(shown, list | tuple) else []
        if kind == Kind.TABLES:
            return (
                [dict(table) for table in shown if isinstance(table, Mapping)]
                if isinstance(shown, list | tuple)
                else []
            )
        if kind == Kind.DATA:
            return self.context.dataText(value)
        if kind == Kind.CHOICE:
            return shown if shown in option.choices else None
        return value

    def _placeholder(self, spec: RowSpec, value: object) -> str:
        option = spec.option
        ph = spec.placeholder() if spec.placeholder else None
        match option.kind:
            case Kind.TEXT | Kind.SECRET | Kind.PATH | Kind.ACTION:
                return unset_text(spec.inherited, ph if spec.placeholder else option.default, "")
            case Kind.DATA:
                return unset_text(spec.inherited, ph)
            case Kind.INTEGER | Kind.NUMBER:
                # without a default of its own, what applies depends on something else: the help says what
                return (unset_text(spec.inherited, ph) or "not set") if option.default is None else ""
            case Kind.CHOICE:
                return unset_text(spec.inherited, ph) if spec.placeholder else ""
            case Kind.BINDING:
                return (
                    f"default: {binding.default_text(option, spec.placeholder)}" if option.base == Kind.CHOICE else ""
                )
            case _:
                return ""

    def _default_help(self, spec: RowSpec) -> str:
        """What a part does unbound, under the help as every default (it may change with other options)."""
        if spec.option.kind == Kind.BINDING and spec.placeholder is not None:
            return spec.placeholder()
        return ""

    def _meaning(self, spec: RowSpec, value: Any) -> str:
        """What the chosen value means; while none is chosen, what the default (the placeholder) means."""
        option = spec.option
        if option.kind == Kind.BINDING:
            chosen = binding.word(option, value, spec.placeholder() if spec.placeholder else None)
            if option.base != Kind.CHOICE and chosen != "homeassistant":
                chosen = None
        elif option.kind == Kind.CHOICE:
            shown = option.default if value is None else value
            chosen = shown if shown in option.choices else None
            if chosen is None and spec.placeholder:
                chosen = spec.placeholder()
        else:
            return ""
        meaning = option.meaning(chosen)
        return f"`{chosen}`: {meaning}" if meaning else ""

    def _matches(self, spec: RowSpec, value: Any) -> dict[str, Any] | None:
        """Under a name: which of the known ones it matches, or that it matches none (None while it is empty)."""
        if spec.option.name not in MATCHED or not callable(spec.suggest) or not isinstance(value, str) or not value:
            return None
        text, found = sources.matches_text(value, spec.suggest())
        return {"text": text, "found": found}

    def _binding_state(self, spec: RowSpec, value: Any) -> dict[str, Any]:
        option = spec.option
        return {
            "mode": binding.mode_of(value),
            "inWords": binding.in_words(option, value),
            "bindTip": binding.bind_tip(option, value),
            "bindTitle": "" if binding.in_words(option, value) else binding.MODE_TITLES[binding.mode_of(value)],
            "channels": spec.channels(),
        }

    def _problems(self, spec: RowSpec, problems: list[Problem]) -> tuple[list[str], dict[str, list[str]]]:
        option = spec.option
        names = spec.names or (spec.name,)

        def below(problem: Problem) -> tuple[int | str, ...]:
            """Where in the option the problem is, e.g. `(2, "label")` of the third table; `()` for itself."""
            at = next((name for name in names if name in problem.path), None)
            return () if at is None else problem.path[problem.path.index(at) + 1 :]

        if option.kind == Kind.BINDING:
            by_column, rest = binding.nested(
                [(below(problem), problem.message) for problem in problems],
                {column.name for column in (*option.columns, *self._table_columns(option))},
            )
            return rest, by_column
        texts: list[str] = []
        for problem in problems:
            rest = below(problem)
            if option.kind != Kind.TABLES or not rest or not isinstance(rest[0], int):
                texts.append(problem.message)
            else:
                texts.append(f"{' '.join([f'{rest[0] + 1}.', *map(str, rest[1:])])}: {problem.message}")
        return texts, {}

    @staticmethod
    def _table_columns(option: Option) -> tuple[Option, ...]:
        from xtouch_daemon.gui.quick.forms.model import table_columns

        return table_columns(option)

    # -- editing ----------------------------------------------------------------------------------------------------

    def coerce(self, option: Option, value: Any) -> Any:
        """The value of a field for the file: empty is none (the default applies), numbers of the kind."""
        if value in ("", []):
            return None
        if option.kind == Kind.INTEGER and isinstance(value, int | float):
            return int(value)
        if option.kind == Kind.NUMBER and isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        if option.kind == Kind.LIST and isinstance(value, list):
            return [str(item) for item in value]  # pyright: ignore[reportUnknownVariableType]
        return value

    def _write(self, spec: RowSpec, value: Any) -> None:
        if spec.put is not None:
            spec.put(value)
        elif value is None:
            self.editor.document.unset(self.path_of(spec))
        else:
            self.editor.document.set(self.path_of(spec), value)

    @pyqtSlot(str, "QVariant")
    def setValue(self, name: str, value: Any) -> None:
        """A field edited the option `name`: into the document, as one step to undo (typing in it merges)."""
        spec = self._specs.get(name)
        if spec is None:
            return
        value = self.coerce(spec.option, value)
        if self._read(spec) == value and (value is not None or self._read(spec) is None):
            return
        self._write(spec, value)
        self.editor.edited(Change(Scope.VALUE, self.path_of(spec)))
        self.edited.emit(name)

    @pyqtSlot(str)
    def reset(self, name: str) -> None:
        """Back to the default: the option is removed."""
        spec = self._specs.get(name)
        if spec is None:
            return
        self._write(spec, None)
        self.editor.edited(Change(Scope.VALUE, self.path_of(spec)))
        self.edited.emit(name)

    revealRequested = pyqtSignal(str, arguments=["name"])

    @pyqtSlot(str)
    def reveal(self, name: str) -> None:
        """Asks the view to show the row of an option and give it the focus."""
        if name in self._specs:
            self.revealRequested.emit(name)

    @pyqtSlot(str, result="QVariant")
    def valueOf(self, name: str) -> Any:
        spec = self._specs.get(name)
        return None if spec is None else plain(self._read(spec))

    # -- suggestions ------------------------------------------------------------------------------------------------

    def _suggester(self, key: str, line: Mapping[str, Any]) -> tuple[Callable[[], tuple[Suggestion, ...]], str, bool]:
        """What a field suggests: the lines, what it says without any, whether they have icons."""
        if key == "@entity":
            source = self.context.entity_source
            return (
                lambda: source.suggestions(),
                (source.why() or "None known").replace("`", ""),
                True,
            )
        if key == "@attribute":
            source = self.context.entity_source
            entity = source.entity(line.get("entity"))
            if not line.get("entity"):
                nothing = "Pick the entity first"
            elif why := source.why():
                nothing = why
            else:
                nothing = "Home Assistant tells no attributes of it" if entity is not None else "The entity is unknown"
            return (lambda: attribute_suggestions(entity), nothing.replace("`", ""), False)
        name, _, column = key.partition(".")
        spec = self._specs.get(name)
        if spec is None:
            return (lambda: (), NO_SUGGESTIONS, False)
        nothing = spec.nothing or NO_SUGGESTIONS_OF.get(name, NO_SUGGESTIONS)
        return (self._column_suggest(spec, column, line), nothing, False)

    @staticmethod
    def _column_suggest(spec: RowSpec, column: str, line: Mapping[str, Any]) -> Suggest:
        """The suggestions of an option, or of a column of a table (the presets of a list first)."""
        suggest = spec.suggest
        found: Suggest | None
        if isinstance(suggest, Mapping):
            fn = suggest.get(column)
            found = (lambda: fn(dict(line))) if fn is not None else None
        else:
            found = suggest
        presets = spec.option.presets
        if presets is None or column:
            return found or (lambda: ())

        def with_presets() -> tuple[Suggestion, ...]:
            return preset_suggestions(presets) + (found() if found is not None else ())

        return with_presets

    @pyqtSlot(str, "QVariantMap", str, str, result="QVariantMap")
    def suggestions(self, key: str, line: dict[str, Any], text: str, mode: str) -> dict[str, Any]:
        """
        The lines of the list under a field for what is typed. `key` is the option (`device`), the column of a table
        (`choices.profile`; `line` has the other values of the entry), `@entity` or `@attribute`.
        """
        suggest, nothing, icons = self._suggester(key, line)
        found = sources.filtered(text, suggest())
        return suggestions.lines(found, text, colors_of(mode), nothing, icons)

    @pyqtSlot(str, "QVariantMap", str, result="QVariantMap")
    def picked(self, key: str, line: dict[str, Any], value: str) -> dict[str, Any]:
        """What else a pick sets: a device only in another profile of its card gives that card and profile."""
        suggest, _, _ = self._suggester(key, line)
        found = next((s for s in suggest() if s.value == value), None)
        if found is None or found.card is None:
            return {}
        return {"card": found.card, "profile": found.profile or ""}

    @pyqtSlot(str, "QVariantMap", str)
    def forget(self, key: str, line: dict[str, Any], value: str) -> None:
        """Forgets a device the daemon remembers (Delete in the list)."""
        suggest, _, _ = self._suggester(key, line)
        found = next((s for s in suggest() if s.value == value), None)
        if found is not None and found.forget is not None:
            found.forget()

    @pyqtSlot(str, str, result="QString")
    def presetTip(self, name: str, value: str) -> str:
        """What a preset in a list says of itself ("Web browsers: firefox, ..."), "" for a name."""
        spec = self._specs.get(name)
        presets = spec.option.presets if spec is not None else None
        return preset_tip(value, presets) if presets is not None else ""

    @pyqtSlot(str, "QVariantMap", result="QVariantMap")
    def entrySummary(self, name: str, entry: dict[str, Any]) -> dict[str, Any]:
        """What an entry of a list of tables says of itself: a title and lines."""
        spec = self._specs.get(name)
        suggest = spec.suggest if spec is not None else None

        def describe_value(column: str, value: object) -> str:
            fn = suggest.get(column) if isinstance(suggest, Mapping) else None
            if fn is None:
                return ""
            found = next((s for s in fn(dict(entry)) if s.value == value), None)
            return tables.trim(found.detail) if found is not None and found.detail else ""

        title, lines = tables.summary(entry, describe_value)
        return {"title": title, "lines": lines}

    # -- buttons ----------------------------------------------------------------------------------------------------

    def _buttons(self, name: str) -> ButtonLogic | None:
        spec = self._specs.get(name)
        return spec.buttons if spec is not None else None

    @pyqtSlot(str, "QVariant", result="QVariantMap")
    def buttonLoad(self, name: str, value: Any) -> dict[str, Any]:
        """The texts of the parts of a button for its value in the file, and the tables kept for the programs."""
        logic = self._buttons(name)
        if logic is None:
            return {"texts": {}, "kept": {}}
        texts, kept = logic.load(value)
        return {"texts": texts, "kept": kept}

    @pyqtSlot(str, "QVariantMap", "QVariantMap", result="QVariantMap")
    def buttonView(self, name: str, texts: dict[str, str], kept: dict[str, Any]) -> dict[str, Any]:
        logic = self._buttons(name)
        return plain(logic.view(texts, kept)) if logic is not None else {"parts": [], "meaning": ""}

    @pyqtSlot(str, "QVariantMap", "QVariantMap", result="QVariantMap")
    def buttonEdit(self, name: str, texts: dict[str, str], kept: dict[str, Any]) -> dict[str, Any]:
        """The value for the texts, and the tables the parts are now (what is in the list is what the parts are)."""
        logic = self._buttons(name)
        if logic is None:
            return {"value": None, "kept": {}}
        value = logic.value(texts, kept)
        return {"value": plain(value), "kept": logic.kept_of(value), "isNone": value is None}

    # -- bindings and tables of entities ----------------------------------------------------------------------------

    @pyqtSlot(str, str, "QVariantMap", result="QVariant")
    def bindValue(self, name: str, mode: str, kept: dict[str, Any]) -> Any:
        """The value for binding the part to `mode` (see `binding.bound_value`)."""
        spec = self._specs.get(name)
        return plain(binding.bound_value(mode, kept, spec.channels() if spec is not None else []))

    @pyqtSlot(str, "QVariantMap", result="double")
    def programStart(self, name: str, table: dict[str, Any]) -> float:
        return binding.number_start(name, table)

    @pyqtSlot(str, "QVariant", str, bool, "QVariantMap", result="QString")
    def entityPlaceholder(self, name: str, default: Any, marker: str, sets: bool, table: dict[str, Any]) -> str:
        entity = self.context.entity_source.entity(table.get("entity"))
        return entity_table.placeholder(name, default, marker, sets, table, entity) or ""

    @pyqtSlot(str, bool, "QVariantMap", result="double")
    def entityStart(self, name: str, sets: bool, table: dict[str, Any]) -> float:
        entity = self.context.entity_source.entity(table.get("entity"))
        return entity_table.start_of(name, table, sets, entity)
