"""
A drop-down list whose list opens inside the window. The list of a `QComboBox` is a popup window: it grabs the
keyboard and the mouse (on X11 the whole display), so the key of a screenshot tool or of the window manager would do
nothing while it is open. This one draws it as a popover, which closes on a click outside, Esc, or a pick.
"""

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QFrame, QListView, QVBoxLayout, QWidget

from xtouch_daemon.gui.qt.fields.depth import lift
from xtouch_daemon.gui.qt.fields.popover import Popover, place
from xtouch_daemon.gui.qt.theme.style import set_role, show_unset
from xtouch_daemon.gui.qt.theme.tokens import Space

ROWS = 12
"""The most rows the list shows at once; it scrolls for more."""


class Choice(QComboBox):
    """
    A `QComboBox` whose list is a popover in its window rather than a popup window. While none of its values is
    chosen, its placeholder (the default, or as where it comes from) is gray, like that of a text field.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.list: QFrame | None = None
        """The list while it is open (or closed, until it is deleted); None for none."""
        self.currentIndexChanged.connect(self._show_unset)
        self._show_unset()

    def _show_unset(self) -> None:
        # an editable one shows its placeholder in its text field, gray already
        show_unset(self, self.currentIndex() < 0 and not self.isEditable())

    def setEditable(self, editable: bool) -> None:
        super().setEditable(editable)
        self._show_unset()

    @property
    def is_open(self) -> bool:
        """Whether the list is open."""
        return self.list is not None and not self.list.isHidden()

    def showPopup(self) -> None:
        if self.is_open:
            self.hidePopup()
            return
        window = self.window()
        if window is None or window is self:
            return
        popover = Popover(self, window)
        set_role(popover, "popup")
        lift(popover)
        popover.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(popover)
        layout.setContentsMargins(Space.XS, Space.XS, Space.XS, Space.XS)
        view = QListView(popover)
        set_role(view, "choice")
        # the row under the mouse is the current one, as in a menu: Enter picks it
        view.setMouseTracking(True)
        view.entered.connect(lambda index: self._hover(view, index))
        view.setModel(self.model())
        view.setModelColumn(self.modelColumn())
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        model = self.model()
        assert model is not None
        view.setCurrentIndex(model.index(self.currentIndex(), self.modelColumn()))
        view.clicked.connect(self._pick)
        view.activated.connect(self._pick)
        layout.addWidget(view)
        rows = max(1, min(self.count(), ROWS))
        height = sum(view.sizeHintForRow(row) for row in range(rows)) + 2 * view.frameWidth()
        width = max(self.width(), view.sizeHintForColumn(0) + 2 * Space.S) - 2 * Space.XS
        if self.count() > ROWS:
            width += view.verticalScrollBar().sizeHint().width()  # type: ignore[union-attr]
        view.setFixedSize(width, height)
        popover.adjustSize()
        popover.move(place(self, window, popover.size()))
        popover.destroyed.connect(lambda _=None, popover=popover: self._closed(popover))
        self.list = popover
        popover.show()
        popover.raise_()
        view.setFocus()
        view.scrollTo(view.currentIndex())

    def hidePopup(self) -> None:
        if self.is_open:
            self.list.close()  # type: ignore[union-attr]
        self.list = None

    def _pick(self, index: QModelIndex) -> None:
        if not self.is_open or not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return  # clicked and activated both: picked once
        row = index.row()
        self.hidePopup()
        self.setCurrentIndex(row)
        self.activated.emit(row)
        self.textActivated.emit(self.itemText(row))
        self.setFocus()

    @staticmethod
    def _hover(view: QListView, index: QModelIndex) -> None:
        if index.flags() & Qt.ItemFlag.ItemIsEnabled:
            view.setCurrentIndex(index)

    def _closed(self, popover: QFrame) -> None:
        if self.list is popover:
            self.list = None
