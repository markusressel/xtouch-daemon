"""
A popover: what a status pill means in full, a click away instead of in a tooltip that takes a while and is easily
missed. Rows of a title, a status, the explanation and buttons, under (or above) the pill.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from xtouch_daemon.gui.domain.status import Status
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, label, show_status
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

TEXT_WIDTH = 380
"""The width of the explanations."""


@dataclass(frozen=True)
class Entry:
    title: str
    """What the row is about, e.g. "Home Assistant"."""
    status: Status | None = None
    """How it is doing, as a pill; None for none."""
    text: str = ""
    """The explanation (the tip of the status when empty)."""
    actions: tuple[tuple[str, Callable[[], object]], ...] = ()
    """Buttons: their text and what they do (the popover closes first)."""


def show_popover(anchor: QWidget, entries: Sequence[Entry]) -> QFrame:
    """Shows `entries` under `anchor` (above it where the screen has no room below), until a click elsewhere."""
    popup = QFrame(anchor, Qt.WindowType.Popup)
    set_role(popup, "popup")
    popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    grid = QGridLayout(popup)
    grid.setContentsMargins(Space.M, Space.M, Space.M, Space.M)
    grid.setHorizontalSpacing(Space.M)
    grid.setVerticalSpacing(Space.XS)
    for index, entry in enumerate(entries):
        grid.addWidget(label(entry.title), 2 * index, 0)
        if entry.status is not None:
            pill = label("", "pill")
            show_status(pill, entry.status)
            pill.setToolTip("")
            grid.addWidget(pill, 2 * index, 1, Qt.AlignmentFlag.AlignLeft)
        if entry.actions:
            buttons = QHBoxLayout()
            for text, action in entry.actions:
                button = QPushButton(text)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.clicked.connect(lambda _=False, action=action: (popup.close(), action()))
                buttons.addWidget(button)
            grid.addLayout(buttons, 2 * index, 2, Qt.AlignmentFlag.AlignRight)
        text = entry.text or (entry.status.tip if entry.status is not None else "")
        if text:
            if " " in text:
                explanation: QLabel = label(text, "hint", wrap=True)
                explanation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            else:
                # a path: it can't wrap, so its middle goes (all of it in its tooltip)
                explanation = ElidedLabel(text, "hint", Qt.TextElideMode.ElideMiddle)
            explanation.setFixedWidth(TEXT_WIDTH)
            explanation.setContentsMargins(0, 0, 0, Space.S)
            grid.addWidget(explanation, 2 * index + 1, 0, 1, 3)
    popup.adjustSize()
    below = anchor.mapToGlobal(QPoint(0, anchor.height() + Space.XS))
    screen = anchor.screen()
    if screen is not None and below.y() + popup.height() > screen.availableGeometry().bottom():
        below = anchor.mapToGlobal(QPoint(0, -popup.height() - Space.XS))
    popup.move(below)
    popup.show()
    return popup


def make_clickable(pill: QLabel, clicked: Callable[[], None]) -> None:
    """A pill that opens a popover (`clicked`); show its status with `show_status(..., more=True)`."""
    pill.setCursor(Qt.CursorShape.PointingHandCursor)

    def press(event: QMouseEvent | None) -> None:
        clicked()

    pill.mousePressEvent = press  # type: ignore[method-assign]
