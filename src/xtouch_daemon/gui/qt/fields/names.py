"""
Fields for names of what the sound server or the voice chat has (devices, cards, profiles, applications, people): a
list that opens on a click and narrows down while typing, and what a value matches.
"""

import html

from PyQt6.QtCore import QEvent, QModelIndex, QObject, QPointF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPainter, QStandardItem, QStandardItemModel, QTextDocument
from PyQt6.QtWidgets import QAbstractItemView, QLineEdit, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.basics import NO_SUGGESTIONS, Suggest
from xtouch_daemon.gui.qt.fields.suggestions import SuggestionList
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import Space

SUGGESTION_ROLE = Qt.ItemDataRole.UserRole + 1
"""The `Suggestion` of a line of the list of a `NameCompleter`."""
QUERY_ROLE = Qt.ItemDataRole.UserRole + 2
"""What was typed when the list was filled: its matches are highlighted."""


def highlighted(text: str, query: str, color: str) -> str:
    """`text` as HTML, with the parts that match `query` (see `sources.spans`) bold in `color`."""
    parts: list[str] = []
    at = 0
    for start, end in sources.spans(text, query):
        parts.append(html.escape(text[at:start]))
        parts.append(f'<b style="color: {color}">{html.escape(text[start:end])}</b>')
        at = end
    parts.append(html.escape(text[at:]))
    return "".join(parts)


def suggestion_html(suggestion: Suggestion | None, query: str, fallback: str = "") -> str:
    """
    A line of the list: what it is (the detail) and where it is known from, and below it the name that goes into the
    option, with the parts that match `query` highlighted; `fallback` for a line that is no suggestion.
    """
    colors = current_colors()
    if suggestion is None:
        return f'<span style="color: {colors.text_muted}">{html.escape(fallback)}</span>'
    origin = suggestion.origin or ("" if suggestion.present else "not there now")
    tag = f'&nbsp;&nbsp;<span style="color: {colors.text_muted}">· {html.escape(origin)}</span>' if origin else ""
    name = highlighted(suggestion.value, query, colors.accent)
    if not suggestion.detail:
        return f"<code>{name}</code>{tag}"
    detail = highlighted(suggestion.detail, query, colors.accent)
    return f'{detail}{tag}<br><code style="color: {colors.text_muted}">{name}</code>'


class SuggestionDelegate(QStyledItemDelegate):
    """Draws a line of the list of a `NameCompleter` (see `suggestion_html`)."""

    def _document(self, index: QModelIndex, width: int) -> QTextDocument:
        document = QTextDocument()
        document.setDocumentMargin(Space.XS)
        document.setHtml(suggestion_html(index.data(SUGGESTION_ROLE), str(index.data(QUERY_ROLE) or ""), index.data()))
        document.setTextWidth(width)
        return document

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        assert painter is not None
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else None
        if style is not None:
            # the line, selected or not, without its text
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, widget)
        document = self._document(index, option.rect.width())
        painter.save()
        painter.translate(QPointF(option.rect.topLeft()))
        document.drawContents(painter)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        # as wide as the list: the lines wrap in it
        view = self.parent()
        viewport = view.viewport() if isinstance(view, QAbstractItemView) else None
        width = viewport.width() if viewport is not None else 0
        document = self._document(index, width if width > 0 else 480)
        return QSize(int(document.idealWidth()), int(document.size().height()))


class NameCompleter(QObject):
    """
    Completes names of what the sound server (or the voice chat) has: the list opens on a click into the field and
    when it gets the focus, and narrows down while typing (by any part of a name or its description, or a pattern
    with `*` and `?`), with the parts that match highlighted. Up/Down and Enter pick one; Esc closes it. The list is a
    popover in the window (see `SuggestionList`), not a popup window.
    """

    activated = pyqtSignal(str, arguments=["name"])
    """A name was picked: it is in the field already."""

    def __init__(self, edit: QLineEdit, suggest: Suggest, nothing: str = NO_SUGGESTIONS):
        super().__init__(edit)  # pyright: ignore[reportArgumentType]
        self.items = QStandardItemModel(self)
        self.edit = edit
        self.suggest = suggest
        self.nothing = nothing
        self.list = SuggestionList(edit, self.items, SuggestionDelegate, rows=8, width=360)
        self.list.picked.connect(lambda index: self.activated.emit(str(index.data())))
        # first: the field has the name before anyone else hears of it
        self.activated.connect(edit.setText)
        edit.textEdited.connect(self.refresh)
        # the stubs of PyQt6 name the wrong type: any QObject filters events
        edit.installEventFilter(self)  # pyright: ignore[reportArgumentType]

    def fill(self, text: str) -> tuple[Suggestion, ...]:
        """The list for what is typed: the suggestions it has."""
        found = sources.filtered(text, self.suggest())
        self.items.clear()
        for suggestion in found:
            item = QStandardItem(suggestion.value)
            item.setData(suggestion, SUGGESTION_ROLE)
            item.setData(text, QUERY_ROLE)
            tip = suggestion.tip or suggestion.detail or suggestion.value
            item.setToolTip(f"{tip}\n\nDelete forgets it." if suggestion.forget is not None else tip)
            item.setEditable(False)
            self.items.appendRow(item)
        if not found:
            item = QStandardItem(f"Nothing known matches {text!r}" if text else self.nothing)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.items.appendRow(item)
        return found

    def refresh(self, text: str | None = None) -> None:
        """Fills the list again, for the text of the field, and shows it."""
        self.fill(self.edit.text() if text is None else text)
        self.list.open()

    def suggestion(self, value: str) -> Suggestion | None:
        """What is known of a value that was picked (e.g. the card and profile of a device of another profile)."""
        return next((suggestion for suggestion in self.suggest() if suggestion.value == value), None)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None or a0 is not self.edit:
            return False
        if self.list.is_open and isinstance(a1, QKeyEvent) and a1.type() == QEvent.Type.KeyPress:
            current = self.list.current()
            suggestion = current.data(SUGGESTION_ROLE) if current.isValid() else None
            if a1.key() == Qt.Key.Key_Delete and isinstance(suggestion, Suggestion) and suggestion.forget is not None:
                # a device the daemon remembers, gone for good
                suggestion.forget()
                self.items.removeRow(current.row())
                return True
        if a1.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress) and not self.list.is_open:
            self.refresh()
        return False


def completer(edit: QLineEdit, suggest: Suggest, nothing: str = NO_SUGGESTIONS) -> NameCompleter:
    """Completes names in `edit` (see `NameCompleter`)."""
    return NameCompleter(edit, suggest, nothing)


def completer_of(edit: QLineEdit) -> NameCompleter | None:
    """The completer of names of `edit`; None for none."""
    return edit.findChild(NameCompleter, options=Qt.FindChildOption.FindDirectChildrenOnly)
