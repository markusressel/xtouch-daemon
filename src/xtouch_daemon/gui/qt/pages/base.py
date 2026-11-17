"""
What the pages share: `Page`, the `Stack` they are in, their titles, and small building blocks (cards, rows,
buttons).
"""

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.slots_document import OptionPath, SlotsDocument, Validation
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, TableSuggest, label
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

type Audio = Callable[[], AudioState]

PAGE_TITLES = {"mqtt": "Home Assistant", "switching": "Modes and chord", "voip": "Voice chat"}
"""The names of the settings for people: the MQTT broker is how Home Assistant is reached."""
SETTINGS_PAGES = ("behavior", "aliases", "mqtt", "switching", "voip", "device")
"""The settings, the ones changed most often first: `[device]` is set once, if ever."""


def page_title(name: str) -> str:
    return PAGE_TITLES.get(name, name.capitalize())


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
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(widget)
    return scroll


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

    def show_part(self, part: QWidget) -> None:
        if part is self.part:
            return
        if self.part is not None:
            self.stack.removeWidget(self.part)
            self.part.hide()
        self.part = part
        self.stack.addWidget(part)
        part.show()


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
