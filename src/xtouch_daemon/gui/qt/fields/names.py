"""
Fields for names of what the sound server or the voice chat has (devices, cards, profiles, applications, people): a
list that opens on a click and narrows down while typing, and what a value matches.
"""

import html

from PyQt6.QtCore import QEvent, QModelIndex, QObject, QPointF, QSize, Qt
from PyQt6.QtGui import QFocusEvent, QPainter, QStandardItem, QStandardItemModel, QTextDocument
from PyQt6.QtWidgets import QAbstractItemView, QCompleter, QLineEdit, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.basics import NO_SUGGESTIONS, Suggest
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


class NameCompleter(QCompleter):
    """
    Completes names of what the sound server (or the voice chat) has: the list opens on a click into the field and
    when it gets the focus, and narrows down while typing (by any part of a name or its description, or a pattern
    with `*` and `?`), with the parts that match highlighted. Up/Down and Enter pick one; Esc closes it.
    """

    def __init__(self, edit: QLineEdit, suggest: Suggest, nothing: str = NO_SUGGESTIONS):
        self.items = QStandardItemModel(edit)
        super().__init__(self.items, edit)
        self.edit = edit
        self.suggest = suggest
        self.nothing = nothing
        self.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.setMaxVisibleItems(8)
        popup = self.popup()
        assert popup is not None
        # kept here: the view does not own its delegate, and Python would drop it
        self.delegate = SuggestionDelegate(popup)
        popup.setItemDelegate(self.delegate)
        popup.setMinimumWidth(360)
        edit.setCompleter(self)
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
            item.setToolTip(suggestion.tip or suggestion.detail or suggestion.value)
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
        self.setCompletionPrefix("")
        self.complete()

    def suggestion(self, value: str) -> Suggestion | None:
        """What is known of a value that was picked (e.g. the card and profile of a device of another profile)."""
        return next((suggestion for suggestion in self.suggest() if suggestion.value == value), None)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        if watched is self.edit and event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
            popup = self.popup()
            back = isinstance(event, QFocusEvent) and event.reason() == Qt.FocusReason.PopupFocusReason
            # not when the focus comes back from the list itself
            if popup is not None and not popup.isVisible() and not back:
                self.refresh()
        return super().eventFilter(watched, event)


def completer(edit: QLineEdit, suggest: Suggest, nothing: str = NO_SUGGESTIONS) -> NameCompleter:
    """Completes names in `edit` (see `NameCompleter`)."""
    return NameCompleter(edit, suggest, nothing)
