"""
The lines of a list of channels, pools or states in the colors of what they are: the name in the hue of its kind
(see `Entity`), the line below in muted text with the states, channels and slots it names in theirs (see `help_text`).
"""

import html
from typing import NamedTuple

from PyQt6.QtCore import QModelIndex, QPointF, QRectF, Qt
from PyQt6.QtGui import QAbstractTextDocumentLayout, QColor, QPainter, QTextDocument
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from xtouch_daemon.gui.qt.fields.basics import DOT, help_text, paint_dot
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space

LINES_ROLE = Qt.ItemDataRole.UserRole + 1


class Lines(NamedTuple):
    """What an item says: its name, the kind it is, and what goes below it."""

    name: str
    entity: Entity
    below: str


class EntityItemDelegate(QStyledItemDelegate):
    """Draws the items that have `Lines` (under `LINES_ROLE`) in color; the text of the item stays the plain one."""

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        lines = index.data(LINES_ROLE)
        if painter is None or not isinstance(lines, Lines):
            super().paint(painter, option, index)
            return
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        item.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        assert style is not None
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, item, widget)
        document = _document(lines, item, rect.width())
        painter.save()
        painter.translate(QPointF(rect.left(), rect.top() + (rect.height() - document.size().height()) / 2))
        painter.setClipRect(QRectF(0, 0, rect.width(), document.size().height()))
        document.documentLayout().draw(painter, QAbstractTextDocumentLayout.PaintContext())  # pyright: ignore[reportOptionalMemberAccess]
        painter.restore()


DOT_ROLE = Qt.ItemDataRole.UserRole + 2
"""Whether the state of an item is on (True), off (False) or not told (None)."""


class DotItemDelegate(QStyledItemDelegate):
    """Draws an item as usual, and the dot of its state (`DOT_ROLE`) after the text of its first line."""

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().paint(painter, option, index)
        on = index.data(DOT_ROLE)
        if painter is None or on is None:
            return
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        assert style is not None
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, item, widget)
        # the item view writes the line breaks as U+2028
        lines = (item.text or "").replace("\n", "\u2028").split("\u2028")
        metrics = item.fontMetrics
        # the lines are centered together; the dot goes in the middle of the first one
        top = rect.top() + (rect.height() - len(lines) * metrics.lineSpacing()) / 2
        # the text starts a little inside its rectangle (the margin of the style)
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget) + 1
        x = rect.left() + margin + metrics.horizontalAdvance(lines[0]) + Space.S + DOT / 2
        paint_dot(painter, QPointF(x, top + metrics.lineSpacing() / 2), bool(on), item.palette.text().color().name())


def _document(lines: Lines, item: QStyleOptionViewItem, width: int) -> QTextDocument:
    # the selected row is a tint (see the style sheet): the hues keep their contrast on it
    colors = current_colors()
    name = getattr(colors, lines.entity)
    below = colors.text_muted
    document = QTextDocument()
    document.setDefaultFont(item.font)
    document.setDocumentMargin(0)
    document.setTextWidth(width)
    text = help_text(lines.below)
    document.setHtml(
        f'<span style="color: {name}">{html.escape(lines.name)}</span><br>'
        f'<span style="color: {QColor(below).name()}">{text}</span>'
    )
    return document
