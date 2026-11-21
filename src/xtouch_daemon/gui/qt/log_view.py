"""
The window Log (a dock of the main window, hidden at first): the log of the running daemon, sent over the live view
(`live.WatchLog`) while the window shows, colored by level, with a filter for the level, a search that marks its
matches, and the end of the log in view while new records come in (Follow).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.domain.log import LEVELS, MAX_MATCHES, LogHistory, line, matches, shown
from xtouch_daemon.gui.domain.status import log_unavailable
from xtouch_daemon.gui.qt.fields.basics import label
from xtouch_daemon.gui.qt.fields.choice import Choice
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.live.messages import EndLog, LogEntry, LogLines, Snapshot, WatchLog

MARK_ALPHA = 110
"""How strongly a match of the search is marked, of 255."""

DEFAULT_LEVEL = "DEBUG"
"""The level the window starts with: everything the daemon logs (it logs debug records only with `-l debug`)."""


class LogView(QWidget):
    """The log of the daemon of `live`, while `set_active(True)` (its dock shows)."""

    def __init__(self, live: LiveView):
        super().__init__()
        self.live = live
        self.history = LogHistory()
        self.active = False
        """Whether the window shows: only then the daemon sends its log."""
        self.watching = False
        """Whether the daemon was asked for its log on this connection (`WatchLog`)."""
        self.match_count = 0
        self.marks: list[QTextEdit.ExtraSelection] = []
        """The matches of the search that are marked, at most `MAX_MATCHES`."""
        self.placed: list[tuple[int, str]] = []
        """The records in the text: where each starts, and its text (more lines for a traceback)."""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.L, Space.S, Space.L, Space.L)
        layout.setSpacing(Space.S)
        bar = QHBoxLayout()
        bar.setSpacing(Space.S)
        self.level = Choice()
        for level in LEVELS:
            self.level.addItem(level.capitalize(), level)
        self.level.setCurrentIndex(LEVELS.index(DEFAULT_LEVEL))
        self.level.setToolTip("The records of this level and above")
        self.level.currentIndexChanged.connect(lambda _index: self.redraw())
        bar.addWidget(label("Level"))
        bar.addWidget(self.level)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Marks the text in the log, ignoring case. Enter goes to the next match.")
        self.search.textChanged.connect(lambda _text: self._mark_all())
        self.search.returnPressed.connect(self.next_match)
        bar.addWidget(self.search, 1)
        self.matches_label = label("", "hint")
        bar.addWidget(self.matches_label)
        self.follow = QPushButton("Follow")
        self.follow.setCheckable(True)
        self.follow.setChecked(True)
        self.follow.setToolTip(
            "Keeps the latest records in view. Scrolling up stops it, scrolling to the end starts it."
        )
        self.follow.toggled.connect(self._follow_toggled)
        bar.addWidget(self.follow)
        layout.addLayout(bar)
        self.message = label("", "hint", wrap=True)
        """Why the log can't come from the daemon now: none runs, it is too old, or it went away."""
        self.message.hide()
        layout.addWidget(self.message)
        self.text = QPlainTextEdit()
        set_role(self.text, "log")
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(self.text, 1)
        self._scrolling = False
        """Whether the window scrolls itself (`_render`, `_append`): that is no hand that stops Follow."""
        scroll = self.text.verticalScrollBar()
        assert scroll is not None
        scroll.valueChanged.connect(self._scrolled)
        live.changed.connect(self._live_changed)
        live.logged.connect(self._logged)
        self._live_changed(live.snapshot)

    # -- the daemon ---------------------------------------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        """The window shows (the daemon sends its log) or not (it stops)."""
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
        if reason is None:
            self.message.hide()
            if self.active and not self.watching and self.live.send(WatchLog()):
                self.watching = True
            return
        why = reason.why
        if snapshot is None and self.history.entries:
            why = f"{why} The log shows the last records of the daemon before."
        self.message.setText(why)
        self.message.show()

    def _logged(self, lines: LogLines) -> None:
        self.history.take(lines)
        if lines.backlog:
            self.redraw()
            return
        level = self._level()
        for entry in lines.entries:
            if shown(entry, level):
                self._append(entry)

    # -- the text -----------------------------------------------------------------------------------------------------

    def _level(self) -> str:
        return str(self.level.currentData())

    def redraw(self) -> None:
        """Draws the records of the level picked again, e.g. for another level or theme."""
        self._scrolling = True
        self.text.clear()
        self._scrolling = False
        self.marks, self.placed, self.match_count = [], [], 0
        for entry in self.history.shown(self._level()):
            self._insert(entry)
        self._show_matches()
        if self.follow.isChecked():
            self._scroll_to_end()

    def _append(self, entry: LogEntry) -> None:
        self._insert(entry)
        self._show_matches()
        if self.follow.isChecked():
            self._scroll_to_end()

    def _insert(self, entry: LogEntry) -> None:
        document = self.text.document()
        assert document is not None
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not document.isEmpty():
            cursor.insertBlock()
        start = cursor.position()
        text = line(entry)
        colors = current_colors()
        muted = QTextCharFormat()
        muted.setForeground(QColor(colors.text_muted))
        body = QTextCharFormat()
        color = {"DEBUG": colors.text_muted, "WARNING": colors.warning, "ERROR": colors.error}.get(entry.level)
        if entry.level == "CRITICAL":
            color = colors.error
            body.setFontWeight(QFont.Weight.Bold)
        if color is not None:
            body.setForeground(QColor(color))
        # the time in the color of hints, the rest in the color of its level
        cursor.insertText(text[:8], muted)
        cursor.insertText(text[8:], body)
        self.placed.append((start, text))
        self._mark(text, start)

    def _scroll_to_end(self) -> None:
        scroll = self.text.verticalScrollBar()
        assert scroll is not None
        self._scrolling = True
        scroll.setValue(scroll.maximum())
        self._scrolling = False

    def _scrolled(self, value: int) -> None:
        if self._scrolling:
            return
        scroll = self.text.verticalScrollBar()
        assert scroll is not None
        at_end = value >= scroll.maximum()
        if at_end != self.follow.isChecked():
            self.follow.setChecked(at_end)

    def _follow_toggled(self, on: bool) -> None:
        if on:
            self._scroll_to_end()

    # -- the search ---------------------------------------------------------------------------------------------------

    def _mark(self, text: str, start: int) -> None:
        """Marks the matches of the search in `text`, which starts at `start` in the document."""
        look = QTextCharFormat()
        # the accent, see through: the color of the level stays readable on it
        background = QColor(current_colors().accent)
        background.setAlpha(MARK_ALPHA)
        look.setBackground(background)
        for offset, length in matches(text, self.search.text()):
            self.match_count += 1
            if len(self.marks) >= MAX_MATCHES:
                continue
            mark = QTextEdit.ExtraSelection()
            cursor = QTextCursor(self.text.document())
            cursor.setPosition(start + offset)
            cursor.setPosition(start + offset + length, QTextCursor.MoveMode.KeepAnchor)
            mark.cursor = cursor
            mark.format = look
            self.marks.append(mark)

    def _mark_all(self) -> None:
        self.marks, self.match_count = [], 0
        for start, text in self.placed:
            self._mark(text, start)
        self._show_matches()

    def _show_matches(self) -> None:
        self.text.setExtraSelections(self.marks)
        if not self.search.text():
            self.matches_label.setText("")
        elif self.match_count == 0:
            self.matches_label.setText("No match")
        else:
            self.matches_label.setText(f"{self.match_count} match{'es' if self.match_count != 1 else ''}")

    def next_match(self) -> None:
        """Selects the next match after the cursor (from the top after the last), which stops Follow."""
        if not self.marks:
            return
        position = self.text.textCursor().selectionEnd()
        target = next((mark for mark in self.marks if mark.cursor.selectionStart() >= position), self.marks[0])
        self.follow.setChecked(False)
        self.text.setTextCursor(target.cursor)
        self.text.ensureCursorVisible()
