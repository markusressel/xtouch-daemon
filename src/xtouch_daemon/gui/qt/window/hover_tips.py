"""
The tip of what is under the mouse, at once and in the footer: a tooltip takes a while and is easily missed, so its
first paragraph shows in place of the status line while the mouse is on a widget that has one (or inside one).
"""

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from xtouch_daemon.gui.qt.app_events import app_events


class HoverTips(QObject):
    def __init__(self, window: QWidget, tip_label: QLabel, status: QWidget) -> None:
        """`tip_label` shows the tip; `status` (the status line) makes room for it meanwhile."""
        # a child of the window: gone with it, and with it its filter and its timer
        super().__init__(window)  # pyright: ignore[reportArgumentType]
        self.main = window
        self.tip_label = tip_label
        self.status = status
        self.tip_label.hide()
        self.timer = QTimer(self)
        """Shows the tip after the Leave of one widget and the Enter of the next one."""
        self.timer.setSingleShot(True)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self._show)
        app_events().watch(self, (QEvent.Type.Enter, QEvent.Type.Leave))

    def stop(self) -> None:
        """The window closes: no more tips (a new zoom opens another window, see `Session`)."""
        app_events().unwatch(self)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        # an Enter or a Leave (see `app_events`)
        if not self.timer.isActive():
            self.timer.start()
        return False

    def _show(self) -> None:
        tip = self.tip_at(QApplication.widgetAt(QCursor.pos()))
        self.tip_label.setText(tip)
        self.tip_label.setVisible(bool(tip))
        self.status.setVisible(not tip)

    def tip_at(self, widget: QWidget | None) -> str:
        """The first paragraph of the tip of `widget` or the next of its parents that has one, in this window."""
        found = ""
        while widget is not None:
            if not found and widget.toolTip():
                found = widget.toolTip()
            if widget is self.main:
                return " ".join(found.split("\n\n")[0].split())
            widget = widget.parentWidget()
        # in another window (a dialog, a menu)
        return ""
