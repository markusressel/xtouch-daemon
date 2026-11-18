"""
The filter of the keys and the wheel of the whole application, which the main window installs while it is open.
"""

from PyQt6.QtCore import QEvent, QObject, QPointF
from PyQt6.QtGui import QKeyEvent, QKeySequence, QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QScrollBar,
    QWidget,
)


def _takes_wheel(widget: QObject | None) -> bool:
    """Whether the wheel would change the value of `widget`: a number, a choice or a slider (not a scroll bar)."""
    return isinstance(widget, QAbstractSpinBox | QComboBox) or (
        isinstance(widget, QAbstractSlider) and not isinstance(widget, QScrollBar)
    )


class InputFilter(QObject):
    """
    Keeps Undo and Redo from the text fields, so the shortcuts of the window undo in the document (a field's own undo
    would leave the document behind), and the wheel from the fields it would change by accident: it scrolls the page
    under them instead.
    """

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and (event.matches(QKeySequence.StandardKey.Undo) or event.matches(QKeySequence.StandardKey.Redo))
        ):
            # kept from the text fields: the shortcuts of the window undo and redo
            event.ignore()
            return True
        if event.type() == QEvent.Type.Wheel and isinstance(event, QWheelEvent) and _takes_wheel(watched):
            # the wheel scrolls the page under a field instead of changing its value by accident
            assert isinstance(watched, QWidget)
            area = watched.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                viewport = area.viewport()
                assert viewport is not None
                QApplication.sendEvent(
                    viewport,
                    QWheelEvent(
                        QPointF(watched.mapTo(viewport, event.position().toPoint())),
                        event.globalPosition(),
                        event.pixelDelta(),
                        event.angleDelta(),
                        event.buttons(),
                        event.modifiers(),
                        event.phase(),
                        event.inverted(),
                    ),
                )
            return True
        return False
