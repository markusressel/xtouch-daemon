"""
The tip of what is under the mouse, at once and in the footer: a tooltip takes a while and is easily missed, so its
first paragraph shows in place of the status line while the mouse is on a widget that has one (or inside one).
"""

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QLabel, QWidget


class HoverTips(QObject):
    def __init__(self, window: QWidget, tip_label: QLabel, status: QWidget) -> None:
        """`tip_label` shows the tip; `status` (the status line) makes room for it meanwhile."""
        # the window keeps it
        super().__init__()
        self.main = window
        self.tip_label = tip_label
        self.status = status
        self.tip_label.hide()
        self._pending = False
        app = QApplication.instance()
        assert app is not None
        app.installEventFilter(self)

    def stop(self) -> None:
        """The window closes: no more tips (a new zoom opens another window, see `Session`)."""
        app = QApplication.instance()
        assert app is not None
        app.removeEventFilter(self)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave) and not self._pending:
            # after the Leave of one widget and the Enter of the next one
            self._pending = True
            QTimer.singleShot(0, self._show)
        return False

    def _show(self) -> None:
        self._pending = False
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
