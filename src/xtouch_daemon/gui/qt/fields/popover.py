"""
A popover: what a status pill means in full, a click away instead of in a tooltip that takes a while and is easily
missed. A heading, then a row per thing: its title (in the color of what it is: a state, a channel), how it is doing
as a pill, the explanation (with `code` and the words for states, channels and slots in their colors, as the help)
and buttons. A bar in the color of its tone runs down each row, and a problem is tinted, so they stand out at once.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, help_text, label, show_status
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space

TEXT_WIDTH = 400
"""The width of the explanations."""


@dataclass(frozen=True)
class Entry:
    title: str
    """What the row is about, e.g. "Home Assistant"."""
    status: Status | None = None
    """How it is doing, as a pill; None for none."""
    text: str = ""
    """The explanation (the tip of the status when empty), with `code` as in the help."""
    actions: tuple[tuple[str, Callable[[], object]], ...] = ()
    """Buttons: their text and what they do (the popover closes first). The first one of a problem stands out."""
    entity: Entity | None = None
    """What the title names (a state, a channel, a slot), in its color; None for something else."""
    path: str | None = None
    """A path to show under the text, in a monospace font (its middle goes where it doesn't fit)."""


def show_popover(anchor: QWidget, heading: str, entries: Sequence[Entry]) -> QFrame:
    """Shows `entries` under `anchor` (above it where the screen has no room below), until a click elsewhere."""
    popup = QFrame(anchor, Qt.WindowType.Popup)
    set_role(popup, "popup")
    popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    layout = QVBoxLayout(popup)
    layout.setContentsMargins(Space.M, Space.M, Space.M, Space.M)
    layout.setSpacing(Space.S)
    layout.addWidget(label(heading, "section"))
    for entry in entries:
        layout.addWidget(_row(popup, entry))
    popup.adjustSize()
    popup.move(_place(anchor, popup.size()))
    popup.show()
    return popup


def _place(anchor: QWidget, size: QSize) -> QPoint:
    """
    Where a popover of `size` goes: under `anchor` (above it where there is no room below), moved left or up to stay
    inside the window, and in any case on the screen.
    """
    screen = anchor.screen()
    area = screen.availableGeometry() if screen is not None else QRect(QPoint(0, 0), size)
    window = anchor.window()
    if window is not None:
        frame = window.frameGeometry().intersected(area)
        if frame.width() >= size.width() and frame.height() >= size.height():
            area = frame
    top_left = anchor.mapToGlobal(QPoint(0, 0))
    x = top_left.x()
    y = top_left.y() + anchor.height() + Space.XS
    if y + size.height() > area.bottom() + 1:
        y = top_left.y() - size.height() - Space.XS
    x = max(area.left(), min(x, area.right() + 1 - size.width()))
    y = max(area.top(), min(y, area.bottom() + 1 - size.height()))
    return QPoint(x, y)


def _row(popup: QFrame, entry: Entry) -> QFrame:
    tone = entry.status.tone if entry.status is not None else Tone.NEUTRAL
    row = QFrame()
    set_role(row, "popover_row")
    row.setProperty("tone", tone.value)
    grid = QGridLayout(row)
    grid.setContentsMargins(Space.M, Space.S, Space.S, Space.S)
    grid.setHorizontalSpacing(Space.M)
    grid.setVerticalSpacing(Space.XS)
    title = label(entry.title)
    title.setStyleSheet("font-weight: bold;")
    if entry.entity is not None:
        title.setStyleSheet(f"font-weight: bold; color: {getattr(current_colors(), entry.entity.value)};")
    grid.addWidget(title, 0, 0)
    if entry.status is not None:
        pill = label("", "pill")
        show_status(pill, entry.status)
        pill.setToolTip("")
        grid.addWidget(pill, 0, 1, Qt.AlignmentFlag.AlignLeft)
    grid.setColumnStretch(1, 1)
    if entry.actions:
        buttons = QHBoxLayout()
        buttons.setSpacing(Space.XS)
        for index, (text, action) in enumerate(entry.actions):
            button = QPushButton(text)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if index == 0 and tone in (Tone.WARN, Tone.BAD):
                # what fixes it
                set_role(button, "primary", "variant")
            button.clicked.connect(lambda _=False, action=action: (popup.close(), action()))
            buttons.addWidget(button)
        grid.addLayout(buttons, 0, 2, Qt.AlignmentFlag.AlignRight)
    line = 1
    text = entry.text or (entry.status.tip if entry.status is not None else "")
    if text:
        explanation = label("", "hint", wrap=True)
        explanation.setTextFormat(Qt.TextFormat.RichText)
        explanation.setText(help_text(text))
        explanation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        explanation.setFixedWidth(TEXT_WIDTH)
        grid.addWidget(explanation, line, 0, 1, 3)
        line += 1
    if entry.path is not None:
        path = ElidedLabel(entry.path, "path", Qt.TextElideMode.ElideMiddle)
        path.setFixedWidth(TEXT_WIDTH)
        grid.addWidget(path, line, 0, 1, 3)
    return row


def make_clickable(pill: QLabel, clicked: Callable[[], None]) -> None:
    """A pill that opens a popover (`clicked`); show its status with `show_status(..., more=True)`."""
    pill.setCursor(Qt.CursorShape.PointingHandCursor)

    def press(event: QMouseEvent | None) -> None:
        clicked()

    pill.mousePressEvent = press  # type: ignore[method-assign]
