"""
The one event filter of the whole application (`gui/qt/app_events.py`).
"""

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.qt.app_events import AppEvents, app_events
from xtouch_daemon.gui.qt.window.main_window import MainWindow


class Recording(QObject):
    def __init__(self, take: bool = False) -> None:
        super().__init__()
        self.take = take
        self.seen: list[QEvent.Type] = []

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        assert a1 is not None
        self.seen.append(a1.type())
        return self.take


def test_a_part_gets_the_kinds_it_watches_until_it_is_gone(qtbot: QtBot):
    events = app_events()
    assert isinstance(events, AppEvents)
    # one per application
    assert app_events() is events
    widget = QWidget()
    qtbot.addWidget(widget)
    first, second = Recording(), Recording(take=True)
    events.watch(first, (QEvent.Type.User,))
    events.watch(second, (QEvent.Type.User, QEvent.Type.MaxUser))

    QApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))
    QApplication.sendEvent(widget, QEvent(QEvent.Type.User))
    # the newest first, and one that takes the event ends it
    assert second.seen == [QEvent.Type.User]
    assert first.seen == []

    sip.delete(second)
    QApplication.sendEvent(widget, QEvent(QEvent.Type.User))
    assert first.seen == [QEvent.Type.User]
    events.unwatch(first)
    QApplication.sendEvent(widget, QEvent(QEvent.Type.User))
    assert first.seen == [QEvent.Type.User]
    assert all(first not in parts for parts in events.wanted.values())


def test_the_window_watches_through_it_while_it_is_open(window: MainWindow):
    wanted = app_events().wanted
    assert window.input_filter in wanted[QEvent.Type.Wheel]
    assert window.input_filter in wanted[QEvent.Type.ShortcutOverride]
    assert window.text_menus in wanted[QEvent.Type.ContextMenu]
    assert window.hover_tips in wanted[QEvent.Type.Enter]

    window.close()
    assert window.input_filter not in wanted[QEvent.Type.Wheel]
    assert window.hover_tips not in wanted[QEvent.Type.Enter]
