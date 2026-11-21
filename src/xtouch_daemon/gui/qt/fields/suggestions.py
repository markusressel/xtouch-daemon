"""
A list of suggestions under a field, inside the window. The list of a `QCompleter` is a popup window: it grabs the
keyboard and the mouse (on X11 the whole display), so the key of a screenshot tool or of the window manager would do
nothing while it is open. This one is a popover, and the field keeps the focus: typing goes on while it shows.
"""

from collections.abc import Callable

from PyQt6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QFrame,
    QLineEdit,
    QListView,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.qt.fields.depth import lift
from xtouch_daemon.gui.qt.fields.popover import Popover
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

type Delegate = Callable[[QListView], QAbstractItemDelegate]
"""Makes the delegate that draws the lines of a list, for its view."""


class SuggestionPopover(Popover):
    """The popover of a `SuggestionList`: a click into its field leaves it open, a click elsewhere closes it."""

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            where = event.globalPosition().toPoint()
            if not _on(self, where) and not _on(self.anchor, where):
                self.close()
            return False
        return super().eventFilter(watched, event)


class SuggestionList(QObject):
    """
    The lines of `model` in a list under `edit`. While it shows, Up and Down (Page Up, Page Down) pick a line, Enter
    or Tab take it (`picked`), and Esc closes it; the field keeps the focus, and loses the list with it.
    """

    picked = pyqtSignal(QModelIndex, arguments=["index"])

    def __init__(
        self,
        edit: QLineEdit,
        model: QAbstractItemModel,
        delegate: Delegate | None = None,
        rows: int = 8,
        width: int = 0,
        first: bool = False,
    ) -> None:
        """
        `delegate` draws the lines (as a list does without), `rows` is the most lines it shows at once (it scrolls for
        more), `width` the least width, and with `first` the first line is picked when it opens.
        """
        super().__init__(edit)  # pyright: ignore[reportArgumentType]
        self.edit = edit
        self.model = model
        self.delegate = delegate
        self.rows = rows
        self.width = width
        self.first = first
        self.popover: SuggestionPopover | None = None
        self.view: QListView | None = None
        self.drawing: QAbstractItemDelegate | None = None
        # the stubs of PyQt6 name the wrong type: any QObject filters events
        edit.installEventFilter(self)  # pyright: ignore[reportArgumentType]

    @property
    def is_open(self) -> bool:
        return self.popover is not None and self.popover.isVisible()

    def open(self, rect: QRect | None = None) -> None:
        """
        Shows the list (again, for lines that changed) under `rect` of the field (the whole field for None), above
        where the window has no room below. Without lines it closes.
        """
        window = self.edit.window()
        if window is None or window is self.edit or self.model.rowCount() == 0:
            self.close()
            return
        if not self.is_open:
            self._build(window)
        popover, view = self.popover, self.view
        assert popover is not None
        assert view is not None
        area = rect if rect is not None else self.edit.rect()
        width = max(self.width, area.width())
        view.setFixedWidth(width - 2 * Space.XS)
        # shown before it is measured: lines that wrap are as high as the width of the list makes them, once it is laid
        # out (nothing is drawn before it is in its place)
        popover.show()
        popover.raise_()
        shown = min(self.model.rowCount(), self.rows)
        for _ in range(2):
            height = sum(view.sizeHintForRow(row) for row in range(shown)) + 2 * view.frameWidth()
            view.setFixedHeight(max(height, 1))
            popover.adjustSize()
        size = popover.size()
        top_left = self.edit.mapTo(window, QPoint(area.left(), 0))
        y = top_left.y() + self.edit.height() + Space.XS
        if y + size.height() > window.height():
            y = top_left.y() - size.height() - Space.XS
        x = max(0, min(top_left.x(), window.width() - size.width()))
        popover.move(x, max(0, min(y, window.height() - size.height())))
        if self.first:
            self._set_current(self._usable(0, 1))
        elif not view.currentIndex().isValid():
            view.setCurrentIndex(QModelIndex())

    def close(self) -> None:
        if self.is_open:
            self.popover.close()  # type: ignore[union-attr]
        self.popover = None
        self.view = None

    def current(self) -> QModelIndex:
        """The line picked with the keys or under the mouse; an invalid index for none."""
        return self.view.currentIndex() if self.view is not None else QModelIndex()

    def _build(self, window: QWidget) -> None:
        popover = SuggestionPopover(self.edit, window)
        set_role(popover, "popup")
        lift(popover)
        popover.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(popover)
        layout.setContentsMargins(Space.XS, Space.XS, Space.XS, Space.XS)
        view = QListView(popover)
        set_role(view, "choice")
        # the field keeps the focus: typing goes on
        view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view.setMouseTracking(True)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setModel(self.model)
        if self.delegate is not None:
            # kept here: the view does not own its delegate, and Python would drop it
            self.drawing = self.delegate(view)
            view.setItemDelegate(self.drawing)
        view.entered.connect(self._hover)
        view.clicked.connect(self._pick)
        layout.addWidget(view)
        popover.destroyed.connect(lambda _=None, popover=popover: self._closed(popover))
        self.popover = popover
        self.view = view

    def _closed(self, popover: SuggestionPopover) -> None:
        if self.popover is popover:
            self.popover = None
            self.view = None

    def _hover(self, index: QModelIndex) -> None:
        if index.flags() & Qt.ItemFlag.ItemIsEnabled:
            self._set_current(index)

    def _set_current(self, index: QModelIndex) -> None:
        if self.view is not None:
            self.view.setCurrentIndex(index)
            if index.isValid():
                self.view.scrollTo(index)

    def _usable(self, start: int, step: int) -> QModelIndex:
        """The first line from `start` on (in the direction of `step`) that can be picked; invalid for none."""
        row = start
        while 0 <= row < self.model.rowCount():
            index = self.model.index(row, 0)
            if index.flags() & Qt.ItemFlag.ItemIsEnabled:
                return index
            row += step
        return QModelIndex()

    def _move(self, by: int) -> None:
        """Picks the line `by` lines down (up for less than 0) that can be picked; the first or last one for none."""
        current = self.current()
        step = 1 if by > 0 else -1
        if not current.isValid():
            self._set_current(self._usable(0 if by > 0 else self.model.rowCount() - 1, step))
            return
        found = self._usable(max(0, min(self.model.rowCount() - 1, current.row() + by)), step)
        self._set_current(found if found.isValid() else current)

    def _pick(self, index: QModelIndex) -> None:
        if not index.isValid() or not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self.close()
        self.picked.emit(index)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None or a0 is not self.edit:
            return False
        kind = a1.type()
        if kind in (QEvent.Type.FocusOut, QEvent.Type.Hide):
            self.close()
            return False
        if kind != QEvent.Type.KeyPress or not isinstance(a1, QKeyEvent) or not self.is_open:
            return False
        key = a1.key()
        page = max(1, self.rows - 1)
        if key == Qt.Key.Key_Down:
            self._move(1)
        elif key == Qt.Key.Key_Up:
            self._move(-1)
        elif key == Qt.Key.Key_PageDown:
            self._move(page)
        elif key == Qt.Key.Key_PageUp:
            self._move(-page)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            current = self.current()
            if not current.isValid():
                # nothing picked: the field takes the key (Enter ends the edit, Tab goes on)
                self.close()
                return False
            self._pick(current)
        elif key == Qt.Key.Key_Escape:
            self.close()
        else:
            return False
        return True


def _on(widget: QWidget, where: QPoint) -> bool:
    """Whether the point `where` of the screen is on `widget`."""
    return widget.rect().contains(widget.mapFromGlobal(where))
