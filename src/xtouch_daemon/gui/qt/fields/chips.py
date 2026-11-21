"""
Lists of names as chips that wrap like text (`Chips`, laid out by `FlowLayout`).
"""

from collections.abc import Callable

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLayout, QLayoutItem, QLineEdit, QWidget, QWidgetItem

from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.domain.sources import preset_tip
from xtouch_daemon.gui.qt.fields.basics import (
    NO_SUGGESTIONS,
    Suggest,
    discard,
    flat_button,
    with_presets,
)
from xtouch_daemon.gui.qt.fields.names import NameCompleter
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import CONTROL_HEIGHT, Space

CHIP_MARGIN = 5
"""The room between a chip and the border of its field, and between two chips."""
FIELD_CHIP_HEIGHT = CONTROL_HEIGHT - 2 - 2 * CHIP_MARGIN
"""A chip in a field: with its margins and the border as high as the other fields."""


class FlowLayout(QLayout):
    """Lays out its widgets in lines, like words (for the chips of a list)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = Space.XS):
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

    def __init__(
        self,
        suggest: Suggest | None,
        placeholder: Callable[[], str] | None = None,
        nothing: str = NO_SUGGESTIONS,
        presets: PresetKind | None = None,
    ):
        """
        `placeholder` says what no value at all means, `nothing` what the suggestions say without any. With `presets`
        the list may have presets of the kind: they are suggested first, and their chips look different and tell what
        they stand for.
        """
        super().__init__()
        self._placeholder = placeholder
        self._presets = presets
        set_role(self, "chips")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.values: list[str] = []
        self.chips: list[QWidget] = []
        self.flow = FlowLayout(self, spacing=CHIP_MARGIN)
        # a chip and the margins make up the height of a field, so a list lines up with the other fields; the same room
        # on every side of a chip
        self.flow.setContentsMargins(CHIP_MARGIN, CHIP_MARGIN, CHIP_MARGIN, CHIP_MARGIN)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Add…")
        self.input.setMinimumWidth(140)
        self.input.returnPressed.connect(lambda: self.add(self.input.text().strip()))
        self.flow.addWidget(self.input)
        if presets is not None:
            suggest = with_presets(presets, suggest)
        self.completer: NameCompleter | None = None
        if suggest is not None:
            # the list opens on a click into the field, the presets first
            self.completer = NameCompleter(self.input, suggest, nothing)
            self.completer.activated.connect(self.add)

    def show_values(self, values: list[str]) -> None:
        if values != self.values:
            # the same chips stay, so showing the document again lays out nothing
            self.values = list(values)
            for chip in self.chips:
                discard(self.flow, chip)
            self.chips = [self._chip(index, value) for index, value in enumerate(self.values)]
            for index, chip in enumerate(self.chips):
                self.flow.insertWidget(index, chip)
        empty = self._placeholder() if self._placeholder and not self.values else None
        self.input.setPlaceholderText(f"Add… ({empty})" if empty else "Add…")
        self.updateGeometry()

    def _chip(self, index: int, value: str) -> QWidget:
        chip = QWidget(self)
        set_role(chip, "chip")
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(chip)
        chip.setFixedHeight(FIELD_CHIP_HEIGHT)
        layout.setContentsMargins(Space.M - 2, 0, 2, 0)
        layout.setSpacing(Space.XS)
        layout.addWidget(QLabel(value))
        tip = preset_tip(value, self._presets) if self._presets is not None else ""
        if tip:
            set_role(chip, "preset", "variant")
            chip.setToolTip(tip)
        remove = flat_button("close", f"Remove {value!r}", chip)
        remove.setFixedSize(FIELD_CHIP_HEIGHT - 4, FIELD_CHIP_HEIGHT - 4)
        remove.setIconSize(QSize(14, 14))
        remove.clicked.connect(lambda: self.remove(index))
        layout.addWidget(remove)
        return chip

    def add(self, value: str) -> None:
        self.input.clear()
        # the completer puts the value it picked into the field after it said so
        QTimer.singleShot(0, self.input.clear)
        if value and value not in self.values:
            self.show_values([*self.values, value])
            self.changed.emit(list(self.values))

    def remove(self, index: int) -> None:
        self.show_values(self.values[:index] + self.values[index + 1 :])
        self.changed.emit(list(self.values))
