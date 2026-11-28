"""
What the pages share: `Page`, the `Stack` they are in, their titles, and small building blocks (cards, rows,
buttons).
"""

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QSize, Qt
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.slots_document import OptionPath, SlotsDocument, Validation
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, TableSuggest, label
from xtouch_daemon.gui.qt.fields.depth import scroll_shadows
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.motion import fading
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

type Audio = Callable[[], AudioState]

PAGE_TITLES = {
    "device": "Extender",
    "mqtt": "Home Assistant",
    "switching": "Modes and chord",
    "voip": "Voice chat",
}
"""The names of the settings for people, in the navigation."""
SECTION_TITLES = {"mqtt": "MQTT broker", "homeassistant": "API"}
"""
The headings of sections that share a page (see `SETTINGS_GROUPS`): the MQTT broker is how Home Assistant is reached,
its API how the entities are.
"""
SETTINGS_PAGES = ("behavior", "aliases", "mqtt", "homeassistant", "switching", "voip", "device")
"""The settings, the ones changed most often first: `[device]` is set once, if ever."""
SETTINGS_GROUPS = {"mqtt": ("mqtt", "homeassistant")}
"""Sections that share an entry of the navigation and a page, one below the other, by the first of them."""


def page_title(name: str) -> str:
    return PAGE_TITLES.get(name, name.capitalize())


def section_title(name: str) -> str:
    """The heading of a section on its page."""
    return SECTION_TITLES.get(name, page_title(name))


def settings_entry(name: str) -> str:
    """The entry of the navigation that shows the section `name`: its own, or the first of its group."""
    return next((first for first, group in SETTINGS_GROUPS.items() if name in group), name)


SETTINGS_NAV = tuple(name for name in SETTINGS_PAGES if settings_entry(name) == name)
"""The entries of the navigation of the settings."""


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    set_role(frame, "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(Space.L, Space.L, Space.L, Space.L)
    layout.setSpacing(Space.S)
    return frame, layout


def row(layout: QLayout) -> QWidget:
    """A widget around a layout, to add it to a page like its other widgets."""
    layout.setContentsMargins(0, 0, 0, 0)
    holder = QWidget()
    holder.setLayout(layout)
    return holder


def scrolled(widget: QWidget) -> QScrollArea:
    """`widget` in an area that scrolls up and down when it is taller than the room it has."""
    # as wide as the area, never wider: a wider least width (e.g. of a row with its name beside its field) would make
    # the area widen it, and at that width the rows would ask for it again, so the layout went back and forth
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(widget)
    scroll_shadows(scroll)
    return scroll


class Flip(QWidget):
    """
    Widgets side by side (e.g. the preview of a part and the options about it) while there is room for them, at least
    `wide` pixels, and one above the other below that.
    """

    def __init__(self, wide: int, spacing: int = Space.L):
        super().__init__()
        self.wide = wide
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(spacing)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        side_by_side = self.box.direction() == QBoxLayout.Direction.LeftToRight
        # a margin both ways: the scroll bar that comes with a taller form must not switch it back
        if side_by_side and self.width() < self.wide:
            self.box.setDirection(QBoxLayout.Direction.TopToBottom)
        elif not side_by_side and self.width() > self.wide + Space.M:
            self.box.setDirection(QBoxLayout.Direction.LeftToRight)


class Sideways(QScrollArea):
    """
    A row of widgets that may grow (e.g. a button per state) and scrolls sideways where the page is too narrow for
    it, so more of them never make the window wider. It is as tall as the row, and its scroll bar while it shows.
    """

    def __init__(self, widget: QWidget):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setWidget(widget)
        widget.installEventFilter(self)
        self.overflows = False
        """Whether the row is wider than the room it has: the scroll bar shows."""

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        if event.type() == QEvent.Type.LayoutRequest:
            # the row changed: maybe its height, maybe whether it fits
            self._check()
            self.updateGeometry()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        if self._check():
            self.updateGeometry()

    def _check(self) -> bool:
        """Whether the row fits, now: True if that changed."""
        widget = self.widget()
        assert widget is not None
        overflows = widget.minimumSizeHint().width() > self.width()
        changed, self.overflows = overflows != self.overflows, overflows
        return changed

    def sizeHint(self) -> QSize:
        widget = self.widget()
        assert widget is not None
        bar = self.horizontalScrollBar()
        assert bar is not None
        height = widget.sizeHint().height() + (bar.sizeHint().height() if self.overflows else 0)
        return QSize(widget.sizeHint().width(), height)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.sizeHint().height())


def button(icon: str, text: str, color: str | None = None, role: str = "") -> QPushButton:
    """A push button with an icon that follows the theme (see `set_icon`), in a style role ("primary", ...)."""
    widget = QPushButton(text)
    set_icon(widget, icon, color)
    if role:
        set_role(widget, role, "variant")
    return widget


def set_text(widget: QLabel | QPushButton, text: str) -> None:
    """A new text, only if it is one: the same text again would still lay out the window again."""
    if widget.text() != text:
        widget.setText(text)


class Stack(QWidget):
    """
    Parts of a page of which one shows at a time, e.g. the form of each strip type. Only the one that shows is in its
    layout, so the page takes its size, not that of the largest part: a short part leaves no gap under it and does not
    stretch its fields. (A `QStackedWidget` does: its layout answers the height for a width with that of the largest
    part, whatever their size policies.)
    """

    def __init__(self) -> None:
        super().__init__()
        self.stack = QVBoxLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.part: QWidget | None = None

    def add(self, part: QWidget) -> None:
        """
        A part, hidden until it shows: it is in the window from the start, so a new theme reaches it (see
        `refresh_icons`) and it goes with the window. A part without a parent would be a window of its own.
        """
        part.setParent(self)
        part.hide()

    def show_part(self, part: QWidget) -> None:
        if part is self.part:
            return
        # the old part fades into the new one (see `gui/qt/motion.py`)
        with fading(self):
            if self.part is not None:
                self.stack.removeWidget(self.part)
                self.part.hide()
            self.part = part
            self.stack.addWidget(part)
            part.show()


EDGE = Space.XL
"""
Room on the right of what a page with panes shows above them: the panes reach the right edge of the window, so the
scroll bar of the right one sits at it (see `MainWindow`).
"""


def edged(page: Page) -> None:
    """A page with panes: they reach the right edge of the window; the rows above them keep `EDGE` from it."""
    margins = page.layout_.contentsMargins()
    page.layout_.setContentsMargins(margins.left(), margins.top(), 0, margins.bottom())
    for index in range(page.layout_.count()):
        item = page.layout_.itemAt(index)
        widget = item.widget() if item is not None else None
        if widget is not None and not isinstance(widget, QSplitter):
            widget.setContentsMargins(0, 0, EDGE, 0)


class Page(QWidget):
    """A page of the editor. `show_document` shows the document again where `change` touches the page."""

    def __init__(self, editor: Editor, audio: Audio):
        super().__init__()
        self.editor = editor
        self.audio = audio
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(Space.XS, Space.XS, Space.M, Space.M)
        self.layout_.setSpacing(Space.M)
        self.option_rows: list[OptionRow] = []
        self.problem = label("", "error", wrap=True)
        """Problems that belong to no row: of the whole section or strip, and unknown options."""
        self.problem.hide()

    @property
    def document(self) -> SlotsDocument:
        return self.editor.document

    @property
    def rows(self) -> list[OptionRow]:
        """The rows of the options the page shows."""
        return self.option_rows

    def show_document(self, change: Change) -> None:
        raise NotImplementedError

    def show_problems(self, validation: Validation) -> None:
        raise NotImplementedError

    def _row(
        self,
        option: Any,
        path: Callable[[str], OptionPath],
        suggest: Suggest | TableSuggest | None = None,
        placeholder: Callable[[], str] | None = None,
        link: str | None = None,
        rows: list[OptionRow] | None = None,
    ) -> OptionRow:
        """
        A row for an option at `path(name)` (the path may depend on what the page shows, e.g. the strip), kept in
        `rows` (those of the page by default).
        """
        name = option.name

        def put(value: Any) -> None:
            if value is None:
                self.document.unset(path(name))
            else:
                self.document.set(path(name), value)

        option_row = OptionRow(option, lambda: self._value(path(name)), put, suggest, placeholder, link)
        option_row.edited.connect(lambda: self.editor.edited(Change(Scope.VALUE, path(name))))
        (self.option_rows if rows is None else rows).append(option_row)
        return option_row

    def _value(self, path: OptionPath) -> Any:
        return self.document.get(path)

    def _load_rows(self, rows: list[OptionRow]) -> None:
        for option_row in rows:
            option_row.load()

    def _show_rest(self, rest: list[str]) -> None:
        set_text(self.problem, "\n".join(rest))
        self.problem.setVisible(bool(rest))

    # -- the entries of the page, for the menu Edit (see `MainWindow`) ----------------------------------------------

    ENTRIES = ""
    """What the list of the page holds, for the window to name it: "candidates", "states"; "" for no list."""

    def entries_focused(self) -> bool:
        """
        Whether the list of the page (candidates, channels, states) has the focus: Copy, Paste, Del and the others
        of the menu Edit are for it then. In a field they edit its text.
        """
        return False

    def copy_entry(self) -> str | None:
        """The entry picked as TOML text, as in the file; None without one."""
        return None

    def paste_entries(self, text: str) -> int:
        """Adds the entries of the page in `text` (TOML) after the one picked, and picks the first; how many."""
        return 0

    def duplicate_entry(self) -> bool:
        """Adds a copy of the entry picked after it, and picks it; False without one."""
        return False

    def remove_entry(self) -> bool:
        """Removes the entry picked, as its button Remove does; False without one."""
        return False

    def rename_entry(self) -> bool:
        """Puts the focus on the id of the entry picked, to type another one; False where it has none."""
        return False
