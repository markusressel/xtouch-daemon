"""
A popover: what a status pill means in full, a click away instead of in a tooltip that takes a while and is easily
missed. A heading, then a row per thing: its title (in the color of what it is: a state, a channel), how it is doing
as a pill, the explanation (with `code` and the words for states, channels and slots in their colors, as the help)
and buttons. A bar in the color of its tone runs down each row, and a problem is tinted, so they stand out at once.
"""

import html
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QSize, Qt
from PyQt6.QtGui import QHideEvent, QKeyEvent, QMouseEvent, QShowEvent
from PyQt6.QtWidgets import QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, help_text, label, show_status
from xtouch_daemon.gui.qt.fields.depth import lift
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space

TEXT_WIDTH = 400
"""The width of the explanations."""


@dataclass(frozen=True)
class Entry:
    title: str
    """What the row is about, e.g. "Home Assistant"; "" for none (the popover is about one thing, its heading)."""
    status: Status | None = None
    """How it is doing, as a pill (none without a text: only the color of the bar); None for none."""
    text: str = ""
    """The explanation (the tip of the status when empty), with `code` as in the help."""
    actions: tuple[tuple[str, Callable[[], object]], ...] = ()
    """Buttons: their text and what they do (the popover closes first). The first one of a problem stands out."""
    entity: Entity | None = None
    """What the title names (a state, a channel, a slot), in its color; None for something else."""
    path: str | None = None
    """A path to show under the text, in a monospace font (its middle goes where it doesn't fit)."""
    items: tuple[tuple[str, str], ...] = ()
    """A list under the text, a line each: the item and a note on it (muted, "" for none)."""
    icon: str = ""
    """An icon before the title (see `theme.icons.icon`), e.g. a speaker for the outputs; "" for none."""
    toggles: tuple[tuple[str, bool, Callable[[bool], object]], ...] = ()
    """
    Switches in a row under the text: their text, whether they are on, and what a click does with the new value. Unlike
    the buttons of `actions`, they leave the popover open, so several can be switched at once.
    """


@dataclass(frozen=True)
class Group:
    """A heading between the rows of a popover: the rows after it are of another kind, e.g. states after the mode."""

    title: str
    text: str = ""
    """What the rows of the group have in common, under the title; "" for nothing."""


def show_popover(
    anchor: QWidget,
    heading: str,
    entries: Sequence[Entry | Group],
    intro: str = "",
    actions: tuple[tuple[str, Callable[[], object]], ...] = (),
) -> QFrame:
    """
    Shows `entries` under `anchor` (above it where the window has no room below), until a click elsewhere, Esc, or
    the window changes its size. `intro` explains the whole of it under the heading; `actions` are buttons next to
    the heading that leave it open (unlike those of the entries), e.g. to read something again and show it anew.

    It is drawn inside the window rather than as a popup window of its own: a popup grabs the keyboard and the mouse
    (on X11 the whole display), so the key of a screenshot tool or of the window manager would do nothing meanwhile.
    """
    window = anchor.window()
    assert window is not None
    popup = Popover(anchor, window)
    set_role(popup, "popup")
    lift(popup)
    popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    layout = QVBoxLayout(popup)
    layout.setContentsMargins(Space.M, Space.M, Space.M, Space.M)
    layout.setSpacing(Space.S)
    top = QHBoxLayout()
    top.setSpacing(Space.XS)
    top.addWidget(label(heading, "section"), 1)
    for text, action in actions:
        button = QPushButton(text)
        # Tab reaches it, a click leaves the focus where it is
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(lambda _=False, action=action: action())
        top.addWidget(button)
    layout.addLayout(top)
    if intro:
        explanation = label("", "hint", wrap=True)
        explanation.setTextFormat(Qt.TextFormat.RichText)
        explanation.setText(help_text(intro))
        explanation.setFixedWidth(TEXT_WIDTH + Space.M + 3)
        layout.addWidget(explanation)
    for entry in entries:
        if isinstance(entry, Group):
            _group(layout, entry)
        else:
            layout.addWidget(_row(popup, entry))
    # the size of the wrapped texts in the font of the style, which the rows get only when polished
    popup.ensurePolished()
    popup.adjustSize()
    popup.move(place(anchor, window, popup.size()))
    popup.show()
    popup.raise_()
    # the keys go to it: Tab to its buttons, Esc closes it, and the focus goes back to the anchor
    popup.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    popup.setFocus()
    return popup


def place(anchor: QWidget, window: QWidget, size: QSize) -> QPoint:
    """
    Where a popover of `size` goes in `window`: under `anchor` (above it where there is no room below), moved left or
    up to stay inside the window.
    """
    top_left = anchor.mapTo(window, QPoint(0, 0))
    x = top_left.x()
    y = top_left.y() + anchor.height() + Space.XS
    if y + size.height() > window.height():
        y = top_left.y() - size.height() - Space.XS
    x = max(0, min(x, window.width() - size.width()))
    y = max(0, min(y, window.height() - size.height()))
    return QPoint(x, y)


class Popover(QFrame):
    """A popover in `window`: it closes on a click outside of it, Esc, its anchor hidden, or the window resized."""

    def __init__(self, anchor: QWidget, window: QWidget) -> None:
        super().__init__(window)
        self.anchor = anchor
        self.host = window
        # an anchor deleted while it shows sends no Hide: the next click would ask a deleted widget where it is
        anchor.destroyed.connect(self._anchor_gone)

    def _anchor_gone(self) -> None:
        self.close()

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        _app().installEventFilter(self)  # pyright: ignore[reportArgumentType]

    def hideEvent(self, event: QHideEvent | None) -> None:
        # before it is deleted: no event may reach the filter of a popover that is half gone
        _app().removeEventFilter(self)  # pyright: ignore[reportArgumentType]
        self._focus_back()
        super().hideEvent(event)

    def _focus_back(self) -> None:
        """The focus goes back to the anchor where it was in the popover, as after a menu, if the anchor takes it."""
        focused = QApplication.focusWidget()
        if focused is not None and focused is not self and not QWidget.isAncestorOf(self, focused):
            return
        anchor = self.anchor
        if not sip.isdeleted(anchor) and anchor.isVisible() and anchor.focusPolicy() != Qt.FocusPolicy.NoFocus:
            anchor.setFocus(Qt.FocusReason.PopupFocusReason)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if event is None:
            return False
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            # by where the click is: a click the popover doesn't take goes on to the window too
            where = event.globalPosition().toPoint()
            if _under(self, where):
                return False
            self.close()
            # a click on the anchor closes it, rather than opening it again
            return _under(self.anchor, where)
        if kind == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
            # before the shortcuts of the window (Esc also ends Simulate)
            event.accept()
            self.close()
            return True
        if (watched is self.host and kind in (QEvent.Type.Resize, QEvent.Type.Move)) or (
            watched is self.anchor and kind == QEvent.Type.Hide
        ):
            self.close()
        return False


def _app() -> QCoreApplication:
    app = QCoreApplication.instance()
    assert app is not None
    return app


def _under(widget: QWidget, where: QPoint) -> bool:
    """Whether the point `where` of the screen is on `widget`."""
    return widget.rect().contains(widget.mapFromGlobal(where))


def _group(layout: QVBoxLayout, group: Group) -> None:
    """The heading of a group of rows, set apart from the rows above it."""
    layout.addSpacing(Space.S)
    layout.addWidget(label(group.title.upper(), "group"))
    if group.text:
        text = label("", "hint", wrap=True)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setText(help_text(group.text))
        text.setFixedWidth(TEXT_WIDTH + Space.M + 3)
        layout.addWidget(text)


def _row(popup: QFrame, entry: Entry) -> QFrame:
    tone = entry.status.tone if entry.status is not None else Tone.NEUTRAL
    row = QFrame()
    set_role(row, "popover_row")
    row.setProperty("tone", tone.value)
    grid = QGridLayout(row)
    grid.setContentsMargins(Space.M, Space.S, Space.S, Space.S)
    grid.setHorizontalSpacing(Space.M)
    grid.setVerticalSpacing(Space.XS)
    if entry.title:
        title = label(entry.title)
        title.setStyleSheet("font-weight: bold;")
        if entry.entity is not None:
            title.setStyleSheet(f"font-weight: bold; color: {getattr(current_colors(), entry.entity.value)};")
        if entry.icon:
            # as high as the text, in its color, before it
            size = title.fontMetrics().height()
            mark = QLabel()
            mark.setPixmap(icon(entry.icon).pixmap(QSize(size, size), row.devicePixelRatioF()))
            heading = QHBoxLayout()
            heading.setContentsMargins(0, 0, 0, 0)
            heading.setSpacing(Space.S)
            heading.addWidget(mark)
            heading.addWidget(title)
            grid.addLayout(heading, 0, 0)
        else:
            grid.addWidget(title, 0, 0)
    if entry.status is not None and entry.status.text:
        pill = label("", "pill")
        show_status(pill, entry.status)
        pill.setToolTip("")
        # without a title, in its place
        grid.addWidget(pill, 0, 1 if entry.title else 0, Qt.AlignmentFlag.AlignLeft)
    grid.setColumnStretch(1, 1)
    buttons = _buttons(popup, entry, tone)
    titled = bool(entry.title) or (entry.status is not None and bool(entry.status.text))
    if buttons is not None and titled:
        grid.addLayout(buttons, 0, 2, Qt.AlignmentFlag.AlignRight)
    line = 1 if titled else 0
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
        line += 1
    for item, note in entry.items:
        shown = label("", wrap=True)
        shown.setTextFormat(Qt.TextFormat.RichText)
        muted = current_colors().text_muted
        extra = f' <span style="color: {muted}">{html.escape(note)}</span>' if note else ""
        shown.setText(f'<span style="color: {muted}">•</span>&nbsp; {html.escape(item)}{extra}')
        shown.setFixedWidth(TEXT_WIDTH)
        grid.addWidget(shown, line, 0, 1, 3)
        line += 1
    if entry.toggles:
        grid.addLayout(_toggles(entry), line, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
        line += 1
    if buttons is not None and not titled:
        # nothing above the text: the buttons go under it
        grid.addLayout(buttons, line, 0, 1, 3, Qt.AlignmentFlag.AlignRight)
    return row


def _buttons(popup: QFrame, entry: Entry, tone: Tone) -> QHBoxLayout | None:
    """The buttons of `entry`, the first one of a problem standing out; None without any."""
    if not entry.actions:
        return None
    buttons = QHBoxLayout()
    buttons.setSpacing(Space.XS)
    for index, (text, action) in enumerate(entry.actions):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if index == 0 and tone in (Tone.WARN, Tone.BAD):
            # what fixes it
            set_role(button, "primary", "variant")
        button.clicked.connect(lambda _=False, action=action: (popup.close(), action()))
        buttons.addWidget(button)
    return buttons


def _toggles(entry: Entry) -> QHBoxLayout:
    """The switches of `entry`, checkable segments in a row."""
    toggles = QHBoxLayout()
    toggles.setSpacing(0)
    for text, on, toggled in entry.toggles:
        button = QPushButton(text)
        set_role(button, "segment", "variant")
        button.setCheckable(True)
        button.setChecked(on)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.toggled.connect(lambda checked, toggled=toggled: toggled(checked))
        toggles.addWidget(button)
    return toggles


OPEN_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
"""The keys that open the popover of a pill with the focus, as they press a button."""


def make_clickable(pill: QLabel, clicked: Callable[[], None]) -> None:
    """
    A pill that opens a popover (`clicked`) on a click, or on Space or Enter once Tab gave it the focus; show its
    status with `show_status(..., more=True)`.
    """
    pill.setCursor(Qt.CursorShape.PointingHandCursor)
    pill.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    set_role(pill, "true", "clickable")
    pill.setAccessibleDescription("Opens the details")

    def press(event: QMouseEvent | None) -> None:
        clicked()

    def key(event: QKeyEvent | None) -> None:
        if event is not None and event.key() in OPEN_KEYS:
            clicked()
        else:
            QLabel.keyPressEvent(pill, event)

    pill.mousePressEvent = press  # type: ignore[method-assign]
    pill.keyPressEvent = key  # type: ignore[method-assign]
