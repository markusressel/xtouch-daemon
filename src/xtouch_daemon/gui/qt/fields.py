"""
The form fields: one row per option, built from its `Option` (kind, choices, bounds, default, help), so an option
added to the configuration shows up without changes here.
"""

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QSizeF, QStringListModel, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from xtouch_daemon.config import Problem
from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt import theme

type Suggest = Callable[[], tuple[Suggestion, ...]]
"""What the sound server has now for an option, asked for every time it is needed."""

CHIP_HEIGHT = 2 * theme.Radius.PILL

LABEL_WIDTH = 144
"""The width of the names of the options, so the fields line up (on the 8 px grid)."""


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        theme.set_role(widget, role)
    widget.setWordWrap(wrap)
    return widget


def help_text(text: str) -> str:
    """Help from a docstring, with `code` in a monospace font."""
    parts = [html.escape(part) for part in text.split("`")]
    return "".join(f"<code>{part}</code>" if i % 2 else part for i, part in enumerate(parts))


def help_label(text: str, role: str) -> QLabel:
    """A label with help from a docstring; always rich text, as Qt would show text without tags as it is."""
    widget = label(help_text(text), role, wrap=True)
    widget.setTextFormat(Qt.TextFormat.RichText)
    return widget


def flat_button(icon: str, tip: str, parent: QWidget | None = None) -> QToolButton:
    button = QToolButton(parent)
    button.setIcon(theme.icon(icon))
    button.setToolTip(tip)
    button.setAutoRaise(True)
    theme.set_role(button, "flat", "variant")
    return button


def completer(edit: QLineEdit, suggest: Suggest) -> QCompleter:
    """Completes what the sound server has, by any part of it."""
    model = QStringListModel(edit)
    result = QCompleter(model, edit)
    result.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    result.setFilterMode(Qt.MatchFlag.MatchContains)
    edit.setCompleter(result)
    edit.textEdited.connect(lambda _: model.setStringList([suggestion.value for suggestion in suggest()]))
    return result


def suggestion_menu(parent: QWidget, suggest: Suggest, pick: Callable[[str], None], empty: str) -> QToolButton:
    """A button with a menu of what the sound server has now; picking one calls `pick` with its value."""
    button = flat_button("menu-down", "Pick from what the sound server has now", parent)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(button)
    button.setMenu(menu)

    def fill() -> None:
        menu.clear()
        suggestions = suggest()
        if not suggestions:
            action = QAction(empty, menu)
            action.setEnabled(False)
            menu.addAction(action)
        for suggestion in suggestions:
            text = f"{suggestion.value}    {suggestion.detail}" if suggestion.detail else suggestion.value
            action = QAction(text, menu)
            action.triggered.connect(lambda _=False, value=suggestion.value: pick(value))
            menu.addAction(action)

    menu.aboutToShow.connect(fill)
    return button


class Switch(QAbstractButton):
    """
    A toggle switch, as tall as a field. Off is an outlined track with a small knob, on a filled one with a large
    knob, so the state shows by shape and position, not only by color.
    """

    TRACK = QSize(40, 24)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # repaints on entering and leaving, for the hover state
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(self.TRACK.width(), theme.CONTROL_HEIGHT)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        colors = theme.current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        track = QRectF(QPointF(0, 0), QSizeF(self.TRACK))
        track.moveCenter(QRectF(self.rect()).center())
        radius = track.height() / 2
        on = self.isChecked()
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors.accent_hover if self.underMouse() else colors.accent))
        else:
            painter.setPen(QPen(QColor(colors.text_muted if self.underMouse() else colors.control_border), 2))
            painter.setBrush(QColor(colors.sunken))
        painter.drawRoundedRect(track.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        knob = QPointF(track.right() - radius if on else track.left() + radius, track.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.on_accent if on else colors.control_border))
        painter.drawEllipse(knob, 8 if on else 6, 8 if on else 6)
        if self.hasFocus():
            # a ring around the knob: it stays inside the widget, which keeps the switch aligned with the fields
            painter.setPen(QPen(QColor(colors.on_accent if on else colors.accent), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(knob, radius - 2, radius - 2)


class Swatch(QAbstractButton):
    """A color of an LCD: a dot of the backlight, ringed and ticked when it is the one."""

    SIZE = 32

    def __init__(self, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.name = name
        self.setCheckable(True)
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        colors = theme.current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QRectF(self.rect()).center()
        if self.isChecked() or self.hasFocus() or self.underMouse():
            ring = colors.accent if self.isChecked() or self.hasFocus() else colors.text_muted
            painter.setPen(QPen(QColor(ring), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 14, 14)
        backlight = QColor(theme.LCD_COLORS[self.name])
        painter.setPen(QPen(QColor(colors.control_border), 1))
        painter.setBrush(backlight)
        painter.drawEllipse(center, 10, 10)
        if self.name == "off":
            # a dark LCD: a slash through it
            painter.setPen(QPen(QColor(theme.LCD_TEXT_OFF), 1.5, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(center + QPointF(-5, 5), center + QPointF(5, -5))
        if self.isChecked():
            # a tick as well, for those who can't tell the ring by its color
            tick = theme.LCD_TEXT if backlight.lightnessF() > 0.5 else "#ffffff"
            pen = QPen(QColor(tick), 2, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(
                QPolygonF([center + QPointF(-4.5, 0), center + QPointF(-1.5, 3), center + QPointF(4.5, -3.5)])
            )


class ColorPicker(QWidget):
    """The colors of an LCD as round swatches."""

    picked = pyqtSignal(str, arguments=["color"])

    def __init__(self, choices: tuple[str, ...]):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.XS)
        self.group = QButtonGroup(self)
        self.swatches: dict[str, Swatch] = {}
        for name in choices:
            swatch = Swatch(name, self)
            self.group.addButton(swatch)
            self.swatches[name] = swatch
            layout.addWidget(swatch)
            swatch.clicked.connect(lambda _=False, name=name: self.picked.emit(name))
        layout.addStretch()

    def show_value(self, name: str) -> None:
        if name in self.swatches:
            self.swatches[name].setChecked(True)
            return
        # a value that is no color: none is checked, the problem says why
        self.group.setExclusive(False)
        for swatch in self.swatches.values():
            swatch.setChecked(False)
        self.group.setExclusive(True)


class NumberToggles(QWidget):
    """Some of the numbers from `minimum` to `maximum`, as buttons that stay pressed (e.g. faders)."""

    changed = pyqtSignal(list, arguments=["numbers"])

    def __init__(self, minimum: int, maximum: int):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.buttons: dict[int, QPushButton] = {}
        for number in range(minimum, maximum + 1):
            button = QPushButton(str(number), self)
            theme.set_role(button, "segment", "variant")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False: self.changed.emit(self.values))
            self.buttons[number] = button
            layout.addWidget(button)
        layout.addStretch()

    @property
    def values(self) -> list[int]:
        return [number for number, button in self.buttons.items() if button.isChecked()]

    def show_values(self, values: list[int]) -> None:
        for number, button in self.buttons.items():
            button.setChecked(number in values)


class FlowLayout(QLayout):
    """Lays out its widgets in lines, like words (for the chips of a list)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = theme.Space.XS):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem | None) -> None:
        assert item is not None
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, move: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line:
                x, y, line = area.x(), y + line + self._spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y() + margins.bottom()


class Chips(QWidget):
    """A list of texts as chips, with a field to add one (and suggestions)."""

    changed = pyqtSignal(list, arguments=["values"])

    def __init__(self, suggest: Suggest | None, placeholder: Callable[[], str] | None = None):
        """`placeholder` says what no value at all means."""
        super().__init__()
        self._placeholder = placeholder
        theme.set_role(self, "chips")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.values: list[str] = []
        self.chips: list[QWidget] = []
        self.flow = FlowLayout(self)
        # a chip and the margins make up the height of a field, so a list lines up with the other fields
        vertical = (theme.CONTROL_HEIGHT - 2 - CHIP_HEIGHT) // 2
        self.flow.setContentsMargins(theme.Space.XS, vertical, theme.Space.XS, vertical)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Add…")
        self.input.setMinimumWidth(140)
        self.input.returnPressed.connect(lambda: self.add(self.input.text().strip()))
        self.flow.addWidget(self.input)
        if suggest is not None:
            completer(self.input, suggest).activated.connect(self.add)
            self.flow.addWidget(suggestion_menu(self, suggest, self.add, "The sound server has none right now"))

    def show_values(self, values: list[str]) -> None:
        self.values = list(values)
        for chip in self.chips:
            self.flow.removeWidget(chip)
            chip.deleteLater()
        self.chips = [self._chip(index, value) for index, value in enumerate(self.values)]
        for index, chip in enumerate(self.chips):
            self.flow.insertWidget(index, chip)
        empty = self._placeholder() if self._placeholder and not self.values else None
        self.input.setPlaceholderText(f"Add… ({empty})" if empty else "Add…")
        self.updateGeometry()

    def _chip(self, index: int, value: str) -> QWidget:
        chip = QWidget(self)
        theme.set_role(chip, "chip")
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(chip)
        chip.setFixedHeight(CHIP_HEIGHT)
        layout.setContentsMargins(theme.Space.M - 2, 0, 2, 0)
        layout.setSpacing(theme.Space.XS)
        layout.addWidget(QLabel(value))
        remove = flat_button("close", f"Remove {value!r}", chip)
        remove.setFixedSize(CHIP_HEIGHT - 4, CHIP_HEIGHT - 4)
        remove.setIconSize(QSize(14, 14))
        remove.clicked.connect(lambda: self.remove(index))
        layout.addWidget(remove)
        return chip

    def add(self, value: str) -> None:
        self.input.clear()
        if value and value not in self.values:
            self.show_values([*self.values, value])
            self.changed.emit(list(self.values))

    def remove(self, index: int) -> None:
        self.show_values(self.values[:index] + self.values[index + 1 :])
        self.changed.emit(list(self.values))


class Tables(QWidget):
    """
    A list of tables with texts and numbers (e.g. the profiles of a strip): a line of fields for each, a button to add
    one. The suggestions are for the value: the first text column without a length limit (a label has one).
    """

    changed = pyqtSignal(list, arguments=["values"])

    def __init__(self, columns: tuple[Option, ...], suggest: Suggest | None):
        super().__init__()
        self.columns = columns
        self._suggest = suggest
        self._suggested = next(
            i for i, column in enumerate(columns) if column.kind == Kind.TEXT and column.max_length is None
        )
        self.values: list[dict[str, str | int]] = []
        self.lines: list[list[QLineEdit]] = []
        self._row_widgets: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.XS)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(theme.Space.XS)
        layout.addLayout(self.rows)
        self.add_button = QPushButton(theme.icon("plus"), "Add", self)
        self.add_button.clicked.connect(self.add)
        add = QHBoxLayout()
        add.addWidget(self.add_button)
        add.addStretch()
        layout.addLayout(add)

    def show_values(self, values: list[dict[str, str | int]]) -> None:
        self.values = [dict(value) for value in values]
        for widget in self._row_widgets:
            self.rows.removeWidget(widget)
            widget.deleteLater()
        self.lines = []
        self._row_widgets = [self._row(index, value) for index, value in enumerate(self.values)]
        for widget in self._row_widgets:
            self.rows.addWidget(widget)

    def _row(self, index: int, value: dict[str, str | int]) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.XS)
        lines: list[QLineEdit] = []
        for column in self.columns:
            edit = QLineEdit(str(value.get(column.name, "")), row)
            edit.setPlaceholderText(column.title)
            edit.setToolTip(help_text(column.help))
            if column.max_length is not None:
                edit.setMaxLength(column.max_length)
            edit.textEdited.connect(lambda text, name=column.name: self._edit(index, name, text))
            lines.append(edit)
        for i, (column, edit) in enumerate(zip(self.columns, lines, strict=True)):
            if i != self._suggested:
                # a label, a number: narrow
                edit.setMaximumWidth(120 if column.kind == Kind.TEXT else 110)
            layout.addWidget(edit, 1 if i == self._suggested else 0)
            if i == self._suggested and self._suggest is not None:
                name = column.name
                completer(edit, self._suggest).activated.connect(lambda text, name=name: self._edit(index, name, text))
                layout.addWidget(
                    suggestion_menu(
                        row, self._suggest, lambda text: self._pick(index, text), "The sound server has none"
                    )
                )
        remove = flat_button("close", "Remove it", row)
        remove.clicked.connect(lambda: self.remove(index))
        layout.addWidget(remove)
        self.lines.append(lines)
        return row

    def _edit(self, index: int, name: str, text: str) -> None:
        column = next(column for column in self.columns if column.name == name)
        if text:
            # a number that isn't one stays text: its problem says so
            self.values[index][name] = int(text) if column.kind == Kind.INTEGER and text.isdigit() else text
        else:
            # a missing value: its problem says it is required
            self.values[index].pop(name, None)
        self.changed.emit([dict(value) for value in self.values])

    def _pick(self, index: int, text: str) -> None:
        self.lines[index][self._suggested].setText(text)
        self._edit(index, self.columns[self._suggested].name, text)

    def add(self) -> None:
        self.show_values([*self.values, {}])
        self.changed.emit([dict(value) for value in self.values])
        self.lines[-1][0].setFocus()

    def remove(self, index: int) -> None:
        self.show_values(self.values[:index] + self.values[index + 1 :])
        self.changed.emit([dict(value) for value in self.values])


class OptionRow(QWidget):
    """
    One option: its name, a field for its kind of value, a button back to the default, the help and its problems.
    `get` returns the value in the file (None: not set), `put` sets it (None: removes it, so the default applies).
    """

    edited = pyqtSignal(arguments=[])

    def __init__(
        self,
        option: Option,
        get: Callable[[], Any],
        put: Callable[[Any], None],
        suggest: Suggest | None = None,
        placeholder: Callable[[], str] | None = None,
    ):
        super().__init__()
        self.option = option
        self._get = get
        self._put = put
        self._placeholder = placeholder
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, theme.Space.XS, 0, theme.Space.XS)
        outer.setSpacing(theme.Space.XS)
        top = QHBoxLayout()
        top.setSpacing(theme.Space.S)
        title = label(option.title + ("  *" if option.required else ""))
        title.setFixedWidth(LABEL_WIDTH)
        title.setToolTip(option.name + (", required" if option.required else ""))
        top.addWidget(title)
        top.addWidget(self._field(option, suggest), 1)
        self.reset = flat_button("restore", f"Back to the default ({self._describe(option.default)})", self)
        self.reset.clicked.connect(self._reset)
        top.addWidget(self.reset)
        outer.addLayout(top)
        details = QVBoxLayout()
        details.setContentsMargins(LABEL_WIDTH + theme.Space.S, 0, 0, 0)
        details.setSpacing(2)
        if option.help:
            details.addWidget(help_label(option.help, "help"))
        if option.kind == Kind.SECRET:
            details.addWidget(label("It is saved as plain text in the configuration file.", "help"))
        self.error = label("", "error", wrap=True)
        self.error.hide()
        details.addWidget(self.error)
        outer.addLayout(details)
        self.load()

    @staticmethod
    def _describe(value: Any) -> str:
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, tuple | list):
            return ", ".join(map(str, value)) or "none"
        return "not set" if value is None else str(value)

    # -- the fields of the kinds ----------------------------------------------------------------------------------

    def _field(self, option: Option, suggest: Suggest | None) -> QWidget:
        match option.kind:
            case Kind.TEXT | Kind.SECRET | Kind.PATH:
                return self._text_field(option)
            case Kind.INTEGER:
                self.spin: QSpinBox | QDoubleSpinBox = QSpinBox(self)
                minimum = int(option.minimum or 0)
                if option.default is None:
                    # one below the minimum is "not set", shown as text
                    self._unset = minimum - 1
                    minimum = self._unset
                self.spin.setRange(minimum, int(option.maximum or 1_000_000))
                self.spin.valueChanged.connect(self._edit_number)
                return self._left(self.spin)
            case Kind.NUMBER:
                self.spin = QDoubleSpinBox(self)
                self.spin.setDecimals(1)
                self.spin.setSingleStep(0.5)
                self.spin.setRange(option.minimum or 0, option.maximum or 1_000_000)
                self.spin.valueChanged.connect(self._edit)
                return self._left(self.spin)
            case Kind.SWITCH:
                self.switch = Switch(self)
                self.switch.toggled.connect(self._edit)
                return self._left(self.switch)
            case Kind.CHOICE:
                self.combo = QComboBox(self)
                self.combo.addItems(list(option.choices))
                self.combo.setMinimumWidth(160)
                self.combo.currentTextChanged.connect(self._edit)
                return self._left(self.combo)
            case Kind.COLOR:
                self.colors = ColorPicker(option.choices)
                self.colors.picked.connect(self._edit)
                self.input = self.colors
                return self.colors
            case Kind.LIST:
                self.chips = Chips(suggest, self._placeholder)
                self.chips.changed.connect(self._edit)
                self.input = self.chips
                return self.chips
            case Kind.NUMBERS:
                self.numbers = NumberToggles(int(option.minimum or 0), int(option.maximum or 0))
                self.numbers.changed.connect(self._edit)
                self.input = self.numbers
                return self.numbers
            case Kind.TABLES:
                self.tables = Tables(option.columns, suggest)
                self.tables.changed.connect(self._edit)
                self.input = self.tables
                return self.tables

    def _left(self, widget: QWidget) -> QWidget:
        """The widget at its own size, on the left."""
        self.input = widget
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        layout.addStretch()
        return container

    def _text_field(self, option: Option) -> QWidget:
        edit = QLineEdit(self)
        self.line = self.input = edit
        if option.max_length is not None:
            edit.setMaxLength(option.max_length)
        edit.textEdited.connect(self._edit)
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.XS)
        layout.addWidget(edit, 1)
        if option.kind == Kind.SECRET:
            # hidden, also from someone looking over the shoulder; the eye shows it
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            reveal = flat_button("eye", "Show it", container)
            reveal.setCheckable(True)
            reveal.toggled.connect(
                lambda shown: edit.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
            )
            layout.addWidget(reveal)
        if option.kind == Kind.PATH:
            browse = flat_button("folder-open", "Choose the file", container)
            browse.clicked.connect(self._browse)
            layout.addWidget(browse)
        return container

    def _browse(self) -> None:
        current = self.line.text() or self.line.placeholderText() or "~"
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose {self.option.title.lower()}", str(Path(current).expanduser())
        )
        if path:
            # the daemon expands ~, which keeps the configuration usable for another user name
            home = str(Path.home())
            self._pick("~" + path[len(home) :] if path.startswith(home + "/") else path)

    def _pick(self, value: str) -> None:
        self.line.setText(value)
        self._edit(value)

    # -- showing and editing --------------------------------------------------------------------------------------

    def load(self) -> None:
        """Shows the value in the file, or the default."""
        value = self._get()
        shown = self.option.default if value is None else value
        self._loading = True
        try:
            match self.option.kind:
                case Kind.TEXT | Kind.SECRET | Kind.PATH:
                    self.line.setText(value if isinstance(value, str) else "")
                    default = self._placeholder() if self._placeholder else self.option.default
                    self.line.setPlaceholderText("" if default is None else str(default))
                case Kind.INTEGER | Kind.NUMBER:
                    # a value of another type shows the default; its problem says what is wrong
                    number = shown if isinstance(shown, int | float) else self.option.default
                    if isinstance(self.spin, QSpinBox):
                        if self.option.default is None:
                            default = self._placeholder() if self._placeholder else "not set"
                            self.spin.setSpecialValueText(f"default: {default}")
                        self.spin.setValue(self._unset if number is None else int(number))
                    else:
                        self.spin.setValue(float(number))
                case Kind.SWITCH:
                    self.switch.setChecked(bool(shown))
                case Kind.CHOICE:
                    self.combo.setCurrentIndex(self.option.choices.index(shown) if shown in self.option.choices else -1)
                    if self._placeholder:
                        # shown while none is chosen
                        self.combo.setPlaceholderText(f"default: {self._placeholder()}")
                case Kind.COLOR:
                    self.colors.show_value(str(shown))
                case Kind.LIST:
                    # a single value may stand alone, e.g. `device = "speaker"`
                    self.chips.show_values([shown] if isinstance(shown, str) else [str(item) for item in shown or ()])
                case Kind.NUMBERS:
                    # a value of another type shows none; its problem says what is wrong
                    self.numbers.show_values(list(shown) if isinstance(shown, list | tuple) else [])
                case Kind.TABLES:
                    # a value of another type shows none; its problem says what is wrong
                    tables = shown if isinstance(shown, list | tuple) else ()
                    self.tables.show_values([dict(table) for table in tables if isinstance(table, dict)])
        finally:
            self._loading = False
        self.reset.setVisible(value is not None and not self.option.required)

    def _edit(self, value: Any) -> None:
        if self._loading:
            return
        if value in ("", []):
            # an empty text or list is none: the default applies (or the option is missing, if it is required)
            value = None
        self._put(value)
        self.reset.setVisible(value is not None and not self.option.required)
        self.edited.emit()

    def _edit_number(self, value: float) -> None:
        self._edit(None if self.option.default is None and value == self._unset else value)

    def _reset(self) -> None:
        self._put(None)
        self.load()
        self.edited.emit()

    def show_problems(self, problems: list[Problem]) -> None:
        self.error.setText("\n".join(self._problem_text(problem) for problem in problems))
        self.error.setVisible(bool(problems))
        theme.set_role(self.input, bool(problems), "problem")

    def _problem_text(self, problem: Problem) -> str:
        """The message, after the table and column for a problem in one of `TABLES` (e.g. "2. label: ...")."""
        rest = problem.path[problem.path.index(self.option.name) + 1 :] if self.option.name in problem.path else ()
        if self.option.kind != Kind.TABLES or not rest or not isinstance(rest[0], int):
            return problem.message
        where = " ".join([f"{rest[0] + 1}.", *map(str, rest[1:])])
        return f"{where}: {problem.message}"
