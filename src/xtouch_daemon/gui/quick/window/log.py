"""
The log of the daemon in the window (`LogPanel.qml`): the records it sends over the live view (`WatchLog`) while the
panel shows, colored by level, with a filter for the level, a search that marks its matches and the end of the log in
view while new records come in (Follow).

The text lives in the `QTextDocument` of the `TextArea` of QML (`attach()`), which this backend fills as the widget
`LogView` filled its text edit: the records are inserted with their colors, and a match of the search is a background
in the same text, so the selection and Ctrl+C of the area work across lines.
"""

from collections.abc import Callable, Mapping

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtQuick import QQuickTextDocument

from xtouch_daemon.gui.domain.log import LEVELS, MAX_ENTRIES, MAX_MATCHES, LogHistory, line, matches, shown
from xtouch_daemon.gui.domain.status import log_unavailable
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.live.messages import EndLog, LogEntry, LogLines, Snapshot, WatchLog

KEPT = MAX_ENTRIES
"""The records the text keeps, as many as the history: the oldest go."""
TRIM_STEP = 500
"""How many records over `KEPT` go at once."""
MARK_ALPHA = 110
"""How strongly a match of the search is marked, of 255."""
DEFAULT_LEVEL = "DEBUG"
"""The level the window starts with: everything the daemon logs (it logs debug records only with `-l debug`)."""


class LogBackend(QObject):
    """The log of the daemon of `live`, while `setActive(True)` (its panel shows)."""

    messageChanged = pyqtSignal(arguments=[])
    levelChanged = pyqtSignal(arguments=[])
    searchChanged = pyqtSignal(arguments=[])
    matchesChanged = pyqtSignal(arguments=[])
    followChanged = pyqtSignal(arguments=[])
    selectRange = pyqtSignal(int, int, arguments=["start", "end"])
    """Select this part of the text (the next match): QML selects it in the area and scrolls to it."""
    scrollToEnd = pyqtSignal(arguments=[])

    def __init__(
        self, live: LiveView, colors: Callable[[], Mapping[str, QColor]], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.live = live
        self.colors = colors
        self.history = LogHistory()
        self.active = False
        """Whether the panel shows: only then the daemon sends its log."""
        self.watching = False
        """Whether the daemon was asked for its log on this connection (`WatchLog`)."""
        self.document: QTextDocument | None = None
        self._level = DEFAULT_LEVEL
        self._search = ""
        self._follow = True
        self._message = ""
        self.marks: list[tuple[int, int]] = []
        """The matches of the search that are marked (start and length in the text), at most `MAX_MATCHES`."""
        self.match_count = 0
        self.placed: list[tuple[int, str]] = []
        """The records in the text: where each starts, and its text (more lines for a traceback)."""
        live.changed.connect(self._live_changed)
        live.logged.connect(self._logged)
        self._live_changed(live.snapshot)

    # -- what QML shows -------------------------------------------------------------------------------------------

    @pyqtProperty("QStringList", constant=True)
    def levels(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return [level.capitalize() for level in LEVELS]

    @pyqtProperty(int, notify=levelChanged)
    def levelIndex(self) -> int:  # pyright: ignore[reportRedeclaration]
        return LEVELS.index(self._level)

    @pyqtSlot(int)
    def setLevelIndex(self, index: int) -> None:
        if 0 <= index < len(LEVELS) and LEVELS[index] != self._level:
            self._level = LEVELS[index]
            self.levelChanged.emit()
            self.redraw()

    @pyqtProperty(str, notify=searchChanged)
    def search(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._search

    @pyqtSlot(str)
    def setSearch(self, text: str) -> None:
        if text != self._search:
            self._search = text
            self.searchChanged.emit()
            self.redraw()

    @pyqtProperty(str, notify=matchesChanged)
    def matchesText(self) -> str:  # pyright: ignore[reportRedeclaration]
        """ "" without a search, "No match", or "3 matches"."""
        if not self._search:
            return ""
        if self.match_count == 0:
            return "No match"
        return f"{self.match_count} match{'es' if self.match_count != 1 else ''}"

    @pyqtProperty(bool, notify=followChanged)
    def follow(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """Whether the latest records stay in view."""
        return self._follow

    @pyqtSlot(bool)
    def setFollow(self, on: bool) -> None:
        if on != self._follow:
            self._follow = on
            self.followChanged.emit()
            if on:
                self.scrollToEnd.emit()

    @pyqtSlot(bool)
    def scrolled(self, at_end: bool) -> None:
        """QML: the user scrolled (to the end or away from it): Follow stops or starts."""
        self.setFollow(at_end)

    @pyqtProperty(str, notify=messageChanged)
    def message(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Why the log can't come from the daemon now (none runs, it is too old, or it went away); "" if it can."""
        return self._message

    # -- the document of the area ---------------------------------------------------------------------------------

    @pyqtSlot(QObject)
    def attach(self, document: QObject) -> None:
        """QML: the `textDocument` of the area the log fills."""
        assert isinstance(document, QQuickTextDocument)
        self.document = document.textDocument()
        self.redraw()

    def text(self) -> str:
        return self.document.toPlainText() if self.document is not None else ""

    # -- the daemon -----------------------------------------------------------------------------------------------

    @pyqtSlot(bool)
    def setActive(self, active: bool) -> None:
        """The panel shows (the daemon sends its log) or not (it stops)."""
        self.active = active
        if active:
            self._live_changed(self.live.snapshot)
        elif self.watching:
            self.live.send(EndLog())
            self.watching = False

    def _live_changed(self, snapshot: Snapshot | None) -> None:
        reason = log_unavailable(snapshot, self.live.owned)
        if snapshot is None:
            # a new connection needs a new watch
            self.watching = False
        message = ""
        if reason is None:
            if self.active and not self.watching and self.live.send(WatchLog()):
                self.watching = True
        else:
            message = reason.why
            if snapshot is None and self.history.entries:
                message = f"{message} The log shows the last records of the daemon before."
        if message != self._message:
            self._message = message
            self.messageChanged.emit()

    def _logged(self, lines: LogLines) -> None:
        self.history.take(lines)
        if lines.backlog:
            self.redraw()
            return
        for entry in lines.entries:
            if shown(entry, self._level):
                self._append(entry)

    # -- the text -------------------------------------------------------------------------------------------------

    @pyqtSlot()
    def redraw(self) -> None:
        """Draws the records of the level picked again, e.g. for another level, search or theme."""
        document = self.document
        if document is None:
            return
        document.clear()
        self.marks, self.placed, self.match_count = [], [], 0
        for entry in self.history.shown(self._level):
            self._insert(entry)
        self.matchesChanged.emit()
        if self._follow:
            self.scrollToEnd.emit()

    def _append(self, entry: LogEntry) -> None:
        self._insert(entry)
        self.matchesChanged.emit()
        if self._follow:
            self.scrollToEnd.emit()

    def _insert(self, entry: LogEntry) -> None:
        document = self.document
        if document is None:
            return
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not document.isEmpty():
            cursor.insertBlock()
        start = cursor.position()
        text = line(entry)
        colors = self.colors()
        muted = QTextCharFormat()
        muted.setForeground(colors["text_muted"])
        body = QTextCharFormat()
        color = {"DEBUG": colors["text_muted"], "WARNING": colors["warning"], "ERROR": colors["error"]}.get(entry.level)
        if entry.level == "CRITICAL":
            color = colors["error"]
            body.setFontWeight(QFont.Weight.Bold)
        if color is not None:
            body.setForeground(color)
        # the time in the color of hints, the rest in the color of its level
        cursor.insertText(text[:8], muted)
        cursor.insertText(text[8:], body)
        self.placed.append((start, text))
        self._mark(text, start)
        if len(self.placed) > KEPT + TRIM_STEP:
            self._trim(len(self.placed) - KEPT)

    def _trim(self, count: int) -> None:
        """Takes the oldest `count` records out of the text: it would grow for as long as the window is open."""
        document = self.document
        assert document is not None
        end = self.placed[count][0]
        cursor = QTextCursor(document)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.placed = [(start - end, text) for start, text in self.placed[count:]]
        # the marks went along in the text: only where they are is placed again
        self.marks, self.match_count = [], 0
        for start, text in self.placed:
            self._mark(text, start, draw=False)

    def _mark(self, text: str, start: int, draw: bool = True) -> None:
        """Marks the matches of the search in `text`, which starts at `start` in the document."""
        document = self.document
        assert document is not None
        look = QTextCharFormat()
        # the accent, see through: the color of the level stays readable on it
        background = QColor(self.colors()["accent"])
        background.setAlpha(MARK_ALPHA)
        look.setBackground(background)
        for offset, length in matches(text, self._search):
            self.match_count += 1
            if len(self.marks) >= MAX_MATCHES:
                continue
            self.marks.append((start + offset, length))
            if draw:
                cursor = QTextCursor(document)
                cursor.setPosition(start + offset)
                cursor.setPosition(start + offset + length, QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(look)

    @pyqtSlot(int)
    def nextMatch(self, after: int) -> None:
        """Selects the next match after the position `after` (the end of the selection; from the top after the last)."""
        if not self.marks:
            return
        start, length = next((mark for mark in self.marks if mark[0] >= after), self.marks[0])
        self.setFollow(False)
        self.selectRange.emit(start, start + length)
