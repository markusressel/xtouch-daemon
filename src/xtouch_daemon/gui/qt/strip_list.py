"""
Every strip of the layout being edited, also those the preview of the 8 strips of the device doesn't reach: where
each one is (on the device, collapsed, waiting), to select it, and a button to add one at the end. Shown while the
layout has more strips than the device or a strip collapses (see `wanted()`).
"""

from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QScrollArea, QWidget

from xtouch_daemon.gui.domain.flow import FlowRow, Where, why_not_add
from xtouch_daemon.gui.domain.looks import StripLook
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.fields import label
from xtouch_daemon.gui.qt.pages import set_text
from xtouch_daemon.hardware import protocol


def wanted(strips: list[dict[str, object]]) -> bool:
    """Whether the list is of use: as many strips as the device has (adding one needs it), or one collapses."""
    return len(strips) >= protocol.STRIPS or any(values.get("collapse") is True for values in strips)


class StripList(QWidget):
    clicked = pyqtSignal(int, arguments=["index"])
    """A strip is clicked: its index in the layout."""
    add = pyqtSignal(arguments=[])
    """Add a strip at the end."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.S)
        layout.addWidget(label("Strips", "hint"))
        holder = QWidget()
        self.row = QHBoxLayout(holder)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.row.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll, 1)
        self.add_button = QPushButton("Add strip")
        theme.set_icon(self.add_button, "plus")
        self.add_button.clicked.connect(self.add.emit)
        layout.addWidget(self.add_button)
        self.group = QButtonGroup(self)
        self.buttons: list[QPushButton] = []

    def show_strips(
        self,
        strips: list[dict[str, object]],
        rows: tuple[FlowRow, ...],
        looks: tuple[StripLook, ...],
        selected: int,
        people: tuple[str | None, ...] = (),
    ) -> None:
        """
        `rows` and `looks` for (at least) each of `strips`; `selected`, the strip whose options are shown; `people`,
        the participant of the voice chat on each strip, if any (see `people_on_strips()`).
        """
        self.setVisible(wanted(strips))
        while len(self.buttons) < len(strips):
            button = QPushButton()
            theme.set_role(button, "nav", "variant")
            button.setCheckable(True)
            index = len(self.buttons)
            button.clicked.connect(self._clicked(index))
            self.group.addButton(button)
            self.row.insertWidget(index, button)
            self.buttons.append(button)
        while len(self.buttons) > len(strips):
            button = self.buttons.pop()
            self.group.removeButton(button)
            button.deleteLater()
        for index, button in enumerate(self.buttons):
            row, look = rows[index], looks[index]
            name = f"{index + 1} {look.label or look.kind}"
            person = people[index] if index < len(people) else None
            if person is not None and person != look.label:
                name += f": {person}"
            set_text(button, f"{name} · {row.text}")
            button.setToolTip(TIPS[row.where].format(name=name))
            if button.isChecked() != (index == selected):
                button.setChecked(index == selected)
        reason = why_not_add(list(strips))
        self.add_button.setEnabled(reason is None)
        self.add_button.setToolTip(reason or "Adds an auto strip at the end of the layout.")

    def _clicked(self, index: int) -> Callable[[], None]:
        return lambda: self.clicked.emit(index)


TIPS = {
    Where.DEVICE: "{name}: on the device now.",
    Where.COLLAPSED: "{name}: it has nothing to control, the strips after it moved up.",
    Where.WAITS: "{name}: waits for a place, the strips before it fill the device.",
}
"""What the tooltip of a strip says about where it is."""
