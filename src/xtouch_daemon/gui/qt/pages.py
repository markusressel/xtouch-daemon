"""The pages of the editor: a strip, a section of options (`[device]`, `[behavior]`, `[mqtt]`), and the aliases."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from xtouch_daemon import protocol
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config import STRIP_TYPES, Config
from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.document import SECTIONS, ConfigDocument, Validation
from xtouch_daemon.gui.domain.looks import look
from xtouch_daemon.gui.domain.schema import Kind, options, strip_models, strip_options
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.fields import OptionRow, Suggest, completer, flat_button, help_text, label, suggestion_menu

type Audio = Callable[[], AudioState]

TYPE_TITLES = {"homeassistant": "Home Assistant"}


def type_title(strip_type: str) -> str:
    return TYPE_TITLES.get(strip_type, strip_type.capitalize())


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    theme.set_role(frame, "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(6)
    return frame, layout


def row(layout: QLayout) -> QWidget:
    """A widget around a layout, so the page can remove it like its other widgets."""
    layout.setContentsMargins(0, 0, 0, 0)
    holder = QWidget()
    holder.setLayout(layout)
    return holder


def doc(model: type[BaseModel]) -> str:
    return " ".join((model.__doc__ or "").split())


class Page(QWidget):
    def __init__(self, document: ConfigDocument, audio: Audio, on_edit: Callable[[], None]):
        super().__init__()
        self.document = document
        self.audio = audio
        self.on_edit = on_edit
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(4, 4, 12, 12)
        self.layout_.setSpacing(10)
        self.rows: list[OptionRow] = []
        self.problem = label("", "error", wrap=True)

    def reload(self) -> None:
        """Builds the page again from the document."""
        raise NotImplementedError

    def show_problems(self, validation: Validation) -> None:
        raise NotImplementedError

    def _clear(self) -> None:
        self.rows = []
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.problem = label("", "error", wrap=True)
        self.problem.hide()

    def _rows(self, layout: QVBoxLayout, rows: list[OptionRow]) -> None:
        for option_row in rows:
            option_row.edited.connect(self.on_edit)
            layout.addWidget(option_row)
            self.rows.append(option_row)

    def _show_rest(self, rest: list[str]) -> None:
        """Problems that belong to no row: of the whole section or strip, and unknown options."""
        self.problem.setText("\n".join(rest))
        self.problem.setVisible(bool(rest))


class SectionPage(Page):
    """A section with options of its own, like `[behavior]`; an optional one (`[mqtt]`) can be added and removed."""

    def __init__(self, section: str, document: ConfigDocument, audio: Audio, on_edit: Callable[[], None]):
        super().__init__(document, audio, on_edit)
        self.section = SECTIONS[section]
        self.reload()

    def reload(self) -> None:
        self._clear()
        name = self.section.name
        header = QHBoxLayout()
        header.addWidget(label(f"[{name}]", "section"))
        header.addStretch()
        present = self.document.has_section(name)
        if self.section.optional and present:
            remove = QPushButton(theme.icon("delete-outline", theme.current_colors().error), f"Remove [{name}]")
            theme.set_role(remove, "danger", "variant")
            remove.clicked.connect(self._remove)
            header.addWidget(remove)
        self.layout_.addWidget(row(header))
        self.layout_.addWidget(label(help_text(self.section.help), "hint", wrap=True))
        self.layout_.addWidget(self.problem)
        frame, layout = card()
        if not present:
            layout.addWidget(label(f"There is no [{name}] section in the file.", wrap=True))
            add = QPushButton(theme.icon("plus", "white"), f"Add [{name}]")
            theme.set_role(add, "primary", "variant")
            add.clicked.connect(self._add)
            buttons = QHBoxLayout()
            buttons.addWidget(add)
            buttons.addStretch()
            layout.addWidget(row(buttons))
        else:
            suggest: dict[str, Suggest] = {"ignore": lambda: sources.patterns(self.audio())}
            self._rows(
                layout,
                [
                    OptionRow(
                        option,
                        lambda option_name=option.name: self.document.get((name, option_name)),
                        lambda value, option_name=option.name: self._put(option_name, value),
                        suggest.get(option.name),
                    )
                    for option in options(self.section.model)
                ],
            )
            if name == "device":
                layout.addWidget(label("A changed [device] section takes a restart of the service.", "help"))
        self.layout_.addWidget(frame)
        self.layout_.addStretch()

    def _put(self, name: str, value: Any) -> None:
        if value is None:
            self.document.unset((self.section.name, name))
        else:
            self.document.set((self.section.name, name), value)

    def _add(self) -> None:
        self.document.add_section(self.section.name)
        self.reload()
        self.on_edit()

    def _remove(self) -> None:
        self.document.remove_section(self.section.name)
        self.reload()
        self.on_edit()

    def show_problems(self, validation: Validation) -> None:
        names = {option_row.option.name for option_row in self.rows}
        self._show_rest(
            [
                problem.message if len(problem.path) == 1 else str(problem)
                for problem in validation.at(self.section.name)
                if len(problem.path) == 1 or problem.path[1] not in names
            ]
        )
        for option_row in self.rows:
            option_row.show_problems(validation.at(self.section.name, option_row.option.name))


class StripPage(Page):
    """The strip selected in the preview: its type and its options, or how to configure it."""

    def __init__(
        self,
        document: ConfigDocument,
        audio: Audio,
        on_edit: Callable[[], None],
        on_strips: Callable[[int], None],
    ):
        super().__init__(document, audio, on_edit)
        self.on_strips = on_strips
        """Called after strips were added, removed, moved or changed type, with the strip to select."""
        self.index = 0

    @property
    def configured(self) -> bool:
        return self.index < len(self.document.strips)

    def show_strip(self, index: int) -> None:
        self.index = index
        self.reload()

    def reload(self) -> None:
        self._clear()
        index = self.index
        header = QHBoxLayout()
        header.addWidget(label(f"Strip {index + 1}", "section"))
        header.addStretch()
        if self.configured:
            for icon, tip, target in (
                ("chevron-left", "Move it to the left", index - 1),
                ("chevron-right", "Move it to the right", index + 1),
            ):
                button = flat_button(icon, f"{tip} (or drag it in the preview)")
                button.setEnabled(0 <= target < len(self.document.strips))
                button.clicked.connect(lambda _=False, target=target: self._move(target))
                header.addWidget(button)
            remove = QPushButton(theme.icon("delete-outline", theme.current_colors().error), "Remove")
            theme.set_role(remove, "danger", "variant")
            remove.setToolTip("Remove the strip: the strips right of it move left, free places are auto strips")
            remove.clicked.connect(self._remove)
            header.addWidget(remove)
        self.layout_.addWidget(row(header))
        if self.configured:
            self._configured()
        else:
            self._not_configured()
        self.layout_.addStretch()

    def _not_configured(self) -> None:
        frame, layout = card()
        layout.addWidget(
            label(
                f"Strip {self.index + 1} is not configured, so it is an <b>auto</b> strip: it takes the next "
                "application that plays and has no strip of its own.",
                wrap=True,
            )
        )
        configure = QPushButton(theme.icon("plus", "white"), f"Configure strip {self.index + 1}")
        theme.set_role(configure, "primary", "variant")
        configure.clicked.connect(self._configure)
        buttons = QHBoxLayout()
        buttons.addWidget(configure)
        buttons.addStretch()
        layout.addWidget(row(buttons))
        self.layout_.addWidget(frame)

    def _configured(self) -> None:
        strip = self.document.strips[self.index]
        models = strip_models()
        types = QHBoxLayout()
        types.setSpacing(0)
        self.types = QButtonGroup(self)
        for name in STRIP_TYPES:
            button = QPushButton(type_title(name))
            theme.set_role(button, "segment", "variant")
            button.setCheckable(True)
            button.setChecked(name == strip.type)
            button.setToolTip(doc(models[name]))
            button.clicked.connect(lambda _=False, name=name: self._set_type(name))
            self.types.addButton(button)
            types.addWidget(button)
        types.addStretch()
        self.layout_.addWidget(row(types))
        strip_type = strip.type
        if strip_type in models:
            self.layout_.addWidget(label(help_text(doc(models[strip_type])), "hint", wrap=True))
        self.layout_.addWidget(self.problem)
        if strip_type is None or strip_type not in models:
            return
        frame, layout = card()
        suggest: dict[str, Suggest] = {"match": lambda: sources.patterns(self.audio())}
        placeholders: dict[str, Callable[[], str]] = {"label": self._default_label}
        if strip_type in ("output", "input"):
            direction = Direction(strip_type)
            suggest["device"] = lambda: sources.devices(self.audio(), direction)
            placeholders["device"] = lambda: f"The default {strip_type}"
        if strip_type == "homeassistant":
            placeholders["id"] = lambda: f"strip_{self.index + 1}"
        rows = [
            OptionRow(
                option,
                lambda name=option.name: self.document.get(("strip", self.index, name)),
                lambda value, name=option.name: self._put(name, value),
                suggest.get(option.name),
                placeholders.get(option.name),
            )
            for option in strip_options(strip_type)
        ]
        # what the strip is about first, how it looks and lights after that
        rows.sort(key=lambda option_row: option_row.option.kind in (Kind.COLOR, Kind.SWITCH, Kind.CHOICE))
        self._rows(layout, rows)
        if not rows:
            layout.addWidget(label("An empty strip has no options.", "hint"))
        self.layout_.addWidget(frame)

    def _default_label(self) -> str:
        values = dict(self.document.strips[self.index].values)
        values.pop("label", None)
        return look(values, self.audio(), dict(self.document.aliases))[1]

    def _put(self, name: str, value: Any) -> None:
        if value is None:
            self.document.unset(("strip", self.index, name))
        else:
            self.document.set(("strip", self.index, name), value)
        if name == "device":
            # the label shown by default follows the device
            for option_row in self.rows:
                if option_row.option.name == "label":
                    option_row.load()

    def _set_type(self, strip_type: str) -> None:
        self.document.set_strip_type(self.index, strip_type)
        self.on_strips(self.index)

    def _configure(self) -> None:
        self.document.configure_up_to(self.index)
        self.on_strips(self.index)

    def _move(self, target: int) -> None:
        self.document.move_strip(self.index, target)
        self.on_strips(target)

    def _remove(self) -> None:
        self.document.remove_strip(self.index)
        self.on_strips(self.index)

    def show_problems(self, validation: Validation) -> None:
        if not self.configured:
            return
        names = {option_row.option.name for option_row in self.rows}
        self._show_rest(
            [
                problem.message if len(problem.path) == 2 else str(problem)
                for problem in validation.at("strip", self.index)
                if len(problem.path) == 2 or problem.path[2] not in names
            ]
        )
        for option_row in self.rows:
            option_row.show_problems(validation.at("strip", self.index, option_row.option.name))


class AliasesPage(Page):
    """The names `auto` strips show for applications."""

    def __init__(self, document: ConfigDocument, audio: Audio, on_edit: Callable[[], None]):
        super().__init__(document, audio, on_edit)
        self.edits: list[tuple[QLineEdit, QLineEdit]] = []
        self.reload()

    def reload(self) -> None:
        self._clear()
        self.edits = []
        self.layout_.addWidget(label("[aliases]", "section"))
        description = Config.model_fields["aliases"].description or ""
        self.layout_.addWidget(label(help_text(description.split(":")[0] + "."), "hint", wrap=True))
        frame, layout = card()
        heading = QHBoxLayout()
        heading.addWidget(label("Application, as the sound server reports it", "help"), 3)
        heading.addWidget(label(f"Label (up to {protocol.LCD_CELL_WIDTH} characters)", "help"), 2)
        heading.addSpacing(64)
        layout.addWidget(row(heading))
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(4)
        layout.addWidget(row(self.rows_layout))
        for name, alias in self.document.aliases:
            self._row(name, alias)
        layout.addWidget(self.problem)
        add = QPushButton(theme.icon("plus"), "Add alias")
        add.clicked.connect(self._add)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addStretch()
        layout.addWidget(row(buttons))
        self.layout_.addWidget(frame)
        self.layout_.addStretch()

    def _row(self, name: str, alias: str) -> QLineEdit:
        line = QHBoxLayout()
        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText("e.g. WEBRTC VoiceEngine")
        alias_edit = QLineEdit(alias)
        alias_edit.setMaxLength(protocol.LCD_CELL_WIDTH)
        alias_edit.setPlaceholderText("e.g. Discord")
        for edit in (name_edit, alias_edit):
            edit.textEdited.connect(self._edited)

        def pick(value: str) -> None:
            name_edit.setText(value)
            self._edited()

        def applications() -> tuple[sources.Suggestion, ...]:
            return sources.applications(self.audio())

        completer(name_edit, applications).activated.connect(pick)
        line.addWidget(name_edit, 3)
        line.addWidget(suggestion_menu(self, applications, pick, "No application plays right now"))
        line.addWidget(alias_edit, 2)
        pair = (name_edit, alias_edit)
        remove = flat_button("close", "Remove the alias")
        remove.clicked.connect(lambda: self._remove(pair))
        line.addWidget(remove)
        self.edits.append(pair)
        self.rows_layout.addWidget(row(line))
        return name_edit

    def _edited(self) -> None:
        self.document.aliases = [(name.text(), alias.text()) for name, alias in self.edits]
        self.on_edit()

    def _add(self) -> None:
        self._row("", "").setFocus()
        self._edited()

    def _remove(self, pair: tuple[QLineEdit, QLineEdit]) -> None:
        del self.document.aliases[self.edits.index(pair)]
        self.reload()
        self.on_edit()

    def show_problems(self, validation: Validation) -> None:
        for name, alias in self.edits:
            problems = validation.at("aliases", name.text())
            theme.set_role(name, any(problem.kind in ("missing", "duplicate") for problem in problems), "problem")
            theme.set_role(alias, any(problem.kind not in ("missing", "duplicate") for problem in problems), "problem")
        self._show_rest([f"{problem.path[-1]!r}: {problem.message}" for problem in validation.at("aliases")])
