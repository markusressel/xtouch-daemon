"""The lines of the list of channels: an item is as tall as its lines are, wrapped at the width of the list."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QStyleOptionViewItem
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.qt.fields.rich_items import LINES_ROLE, EntityItemDelegate, Lines
from xtouch_daemon.gui.qt.theme.tokens import Entity


def test_an_item_is_as_tall_as_its_wrapped_lines(qtbot: QtBot):
    view = QListWidget()
    qtbot.addWidget(view)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    delegate = EntityItemDelegate(view)
    view.setItemDelegate(delegate)
    view.setResizeMode(QListWidget.ResizeMode.Adjust)
    below = "the outputs and inputs that no channel has, e.g. a USB headset"
    item = QListWidgetItem(f"Devices\n{below}")
    item.setData(LINES_ROLE, Lines("Devices", Entity.CHANNEL, below))
    view.addItem(item)
    plain = QListWidgetItem("Plain")
    view.addItem(plain)

    def size(width: int, row: int = 0):
        view.resize(width, 300)
        view.show()
        qtbot.waitExposed(view)
        option = QStyleOptionViewItem()
        option.widget = view
        return delegate.sizeHint(option, view.model().index(row, 0))  # type: ignore[union-attr]

    wide = size(900)
    narrow = size(150)
    assert narrow.height() > wide.height()
    assert narrow.width() <= 150
    assert view.visualItemRect(item).height() == narrow.height()
    # an item without lines is as the style has it
    assert size(150, 1).height() < wide.height()
