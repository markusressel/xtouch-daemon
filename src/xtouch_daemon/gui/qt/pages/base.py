"""
What the pages share: `Page`, the `Stack` they are in, their titles, and small building blocks (cards, rows,
buttons).
"""

from collections.abc import Callable
from typing import Any

from PyQt6.QtWidgets import QFrame, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.drafts import Validation
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, TableSuggest, label
from xtouch_daemon.gui.qt.fields.option_row import OptionRow

type Audio = Callable[[], AudioState]

TYPE_TITLES = {"homeassistant": "Home Assistant", "voip": "VoIP"}
PAGE_TITLES = {"mqtt": "Home Assistant", "switching": "Layouts", "voip": "Voice chat"}
"""The names of the global settings for people: the MQTT broker is how Home Assistant is reached."""
GLOBAL_PAGES = ("behavior", "aliases", "mqtt", "switching", "voip", "device")
"""The global settings, the ones changed most often first: `[device]` is set once, if ever."""
LAYOUT_TYPES = ("inherit",)
"""The strip types only the strips of a `[[layout]]` have."""


def page_title(name: str) -> str:
    return PAGE_TITLES.get(name, name.capitalize())


def type_title(strip_type: str) -> str:
    return TYPE_TITLES.get(strip_type, strip_type.capitalize())


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    theme.set_role(frame, "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(theme.Space.L, theme.Space.L, theme.Space.L, theme.Space.L)
    layout.setSpacing(theme.Space.S)
    return frame, layout


def row(layout: QLayout) -> QWidget:
    """A widget around a layout, to add it to a page like its other widgets."""
    layout.setContentsMargins(0, 0, 0, 0)
    holder = QWidget()
    holder.setLayout(layout)
    return holder


def button(icon: str, text: str, color: str | None = None, role: str = "") -> QPushButton:
    """A push button with an icon that follows the theme (see `theme.set_icon`), in a style role ("primary", ...)."""
    widget = QPushButton(text)
    theme.set_icon(widget, icon, color)
    if role:
        theme.set_role(widget, role, "variant")
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
        self.layout_.setContentsMargins(theme.Space.XS, theme.Space.XS, theme.Space.M, theme.Space.M)
        self.layout_.setSpacing(theme.Space.M)
        self.option_rows: list[OptionRow] = []
        self.problem = label("", "error", wrap=True)
        """Problems that belong to no row: of the whole section or strip, and unknown options."""
        self.problem.hide()

    @property
    def document(self) -> ConfigDocument:
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
        path: Callable[[str], tuple[str | int, ...]],
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

    def _value(self, path: tuple[str | int, ...]) -> Any:
        return self.document.get(path)

    def _load_rows(self, rows: list[OptionRow]) -> None:
        for option_row in rows:
            option_row.load()

    def _show_rest(self, rest: list[str]) -> None:
        set_text(self.problem, "\n".join(rest))
        self.problem.setVisible(bool(rest))
