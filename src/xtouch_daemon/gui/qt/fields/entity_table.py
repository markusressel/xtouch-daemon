"""
The options of a table with an entity of Home Assistant, a row each: of a part bound to an entity (`entity`,
`attribute`, `min`, ...) or of a press that calls a service (`service`, `entity`, `data`). The entity and its
attribute have suggestions of what Home Assistant has (see `fields.entities`); an unset option says what it does by
the domain of the entity, e.g. `default: 255, of a light`.
"""

import dataclasses
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QVBoxLayout

from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain.entities import attribute_suggestions, value_placeholder
from xtouch_daemon.gui.domain.schema import Kind, options
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.basics import help_label
from xtouch_daemon.gui.qt.fields.entities import EntityHint, SuggestionList, attach_entity_list, source_of
from xtouch_daemon.homeassistant.states import EntityState

if TYPE_CHECKING:
    from xtouch_daemon.gui.qt.fields.option_row import OptionRow

DEFAULT_ENCODER_STEP = BehaviorConfig.model_fields["encoder_step"].default
"""Percent of the range one step of the encoder is by default (`behavior.encoder_step`)."""
PLACEHOLDERS: dict[str, str] = {
    "step": "behavior.encoder_step % of the range",
    "push": "none: a push does nothing",
}
"""What an unset option does, where its default is no value and the entity does not change it."""


class EntityTable(QFrame):
    """
    The options of a table of `model` (e.g. `EntityValueBinding`, `ServiceAction`), without those in `skip`, with
    its docstring above them. `marker` is the option that makes the table what it is (`entity`, `service`): it stays
    in it while empty. `changed` has the table.
    """

    changed = pyqtSignal(object, arguments=["table"])

    def __init__(self, model: type[BaseModel], marker: str, skip: tuple[str, ...] = (), intro: bool = True) -> None:
        # here, not at the top: option_row imports the modules of the fields that import this one
        from xtouch_daemon.gui.qt.fields.option_row import NumberSpin, OptionRow, align_titles

        super().__init__()
        self.model = model
        self.marker = marker
        self.table: dict[str, Any] = {marker: ""}
        self.sets = "min" in model.model_fields and "service" in model.model_fields
        """A value that a fader or an encoder sets (`EntityValueBinding`): the domain decides what is unset."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if intro:
            layout.addWidget(help_label(" ".join((model.__doc__ or "").split()), "hint"))
        self.rows: dict[str, OptionRow] = {}
        self.entity_list: SuggestionList | None = None
        """The suggestions of the field of the entity."""
        self.attribute_list: SuggestionList | None = None
        self.hint = EntityHint()
        """Why the field of the entity has no suggestions."""
        for column in options(model, skip=skip):
            if column.kind == Kind.NUMBER:
                column = dataclasses.replace(column, signed=True)
            row = OptionRow(
                column,
                lambda name=column.name: self.table.get(name),
                lambda value, name=column.name: self._put(name, value),
                placeholder=self._placeholder(column.name, column.default),
            )
            if isinstance(spin := getattr(row, "spin", None), NumberSpin):
                spin.start = self._start_of(column.name)
            self.rows[column.name] = row
            layout.addWidget(row)
            if column.name == "entity":
                self.entity_list = attach_entity_list(row.line, self, self.hint)
                self.entity_list.picked.connect(row._edit_text)  # pyright: ignore[reportPrivateUsage]
                row.details.insertWidget(0, self.hint)
            elif column.name == "attribute":
                self.attribute_list = SuggestionList(row.line, self._attributes, self._no_attributes)
                self.attribute_list.picked.connect(row._edit_text)  # pyright: ignore[reportPrivateUsage]
        align_titles(self.rows.values())

    # -- what an unset option does ---------------------------------------------------------------------------------

    def _placeholder(self, name: str, default: object) -> Callable[[], str] | None:
        if name in PLACEHOLDERS:
            return lambda: PLACEHOLDERS[name]
        match name:
            case "entity":
                return lambda: "e.g. light.desk" if self.marker == "entity" else "default: none"
            case "service":
                if not self.sets:
                    return lambda: "e.g. light.toggle"
            case "data":
                if not self.sets:
                    return lambda: "none"
            case "attribute":
                if not self.sets:
                    return lambda: "default: none: the state"
            case _:
                pass
        if not self.sets or default is not None:
            return None
        # a text says "default:" itself, a number and the data get it from their row
        before = "default: " if name in ("attribute", "service") else ""
        return lambda: before + (value_placeholder(name, self.table, self.entity()) or "")

    def _start_of(self, name: str) -> Callable[[], float]:
        """Where a number starts once it is set: in the range by the domain of the entity."""

        def number(key: str, fallback: float) -> float:
            value = self.table.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
            if not self.sets:
                return fallback
            try:
                return float((value_placeholder(key, self.table, self.entity()) or "").split(",")[0])
            except ValueError:
                return fallback

        def start() -> float:
            low, high = number("min", 0), number("max", 100)
            if high <= low:
                low, high = 0, 100
            if name == "step":
                return (high - low) * DEFAULT_ENCODER_STEP / 100
            return high if name == "max" else low

        return start

    # -- the entity --------------------------------------------------------------------------------------------------

    def entity(self) -> EntityState | None:
        """The entity of the table as Home Assistant has it, None for one it does not know (or none)."""
        source = source_of(self)
        return source.entity(self.table.get("entity")) if source is not None else None

    def _attributes(self) -> tuple[Suggestion, ...]:
        return attribute_suggestions(self.entity())

    def _no_attributes(self) -> str:
        if not self.table.get("entity"):
            return "Pick the entity first"
        source = source_of(self)
        if source is not None and (why := source.why()):
            return why
        return "Home Assistant tells no attributes of it" if self.entity() is not None else "The entity is unknown"

    def want(self) -> None:
        """The table shows: the entities for the suggestions, and why there are none."""
        if self.entity_list is not None:
            self.entity_list.wanted()

    # -- showing and editing -----------------------------------------------------------------------------------------

    def show_table(self, table: Mapping[str, Any]) -> None:
        self.table = dict(table)
        for row in self.rows.values():
            row.load()

    def _put(self, name: str, value: Any) -> None:
        if value is None and name != self.marker:
            self.table.pop(name, None)
        else:
            self.table[name] = "" if value is None else value
        if name in ("entity", "attribute"):
            # what the others do by default depends on them; the row being edited stays as it is
            for other, row in self.rows.items():
                if other != name:
                    row.load()
        self.changed.emit(dict(self.table))
