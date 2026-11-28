"""
The keys that need a filter on the whole application: Undo and Redo go to the document also while a text field has the
focus (a field's own undo would leave the document behind). The fields of QML take the keys of their editing as
`ShortcutOverride`; the filter lets that one go unanswered, so the shortcut of the window fires.
"""

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QKeyEvent, QKeySequence


class UndoKeys(QObject):
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
        return False
