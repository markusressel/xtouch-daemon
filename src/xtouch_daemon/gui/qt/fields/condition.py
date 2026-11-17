"""
A field for a condition (`gaming and not present`): its words in the colours of what they are, mistakes underlined,
and the words it can take offered while typing (Ctrl+Space offers them at any time).
"""

import re
from collections.abc import Iterable

from PyQt6.QtCore import QCoreApplication, QEvent, QStringListModel, Qt
from PyQt6.QtGui import QColor, QFont, QInputMethodEvent, QKeyEvent, QTextCharFormat, QTextFormat
from PyQt6.QtWidgets import QCompleter, QLineEdit

from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.slots.expressions import ExpressionError, parse

KEYWORDS = ("and", "or", "not", "present")
_WORD = re.compile(r"[a-z0-9_]+|[()]")
_PARTIAL = re.compile(r"[a-z0-9_(]*$")
"""The word being typed, up to the cursor: `pres`, `present(ga`."""


class ConditionEdit(QLineEdit):
    """A one-line field for a condition, with the states and the channels of the file it may name (see `set_names`)."""

    def __init__(self) -> None:
        super().__init__()
        self.states: frozenset[str] = frozenset()
        self.targets: frozenset[str] = frozenset()
        self.words = QStringListModel(self)
        self.completer_ = QCompleter(self.words, self)
        self.completer_.setWidget(self)
        self.completer_.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer_.activated.connect(self._complete)
        self.textChanged.connect(lambda _: self._highlight())
        self.textEdited.connect(lambda _: self._offer(False))

    def set_names(self, states: Iterable[str], targets: Iterable[str]) -> None:
        """The states and modes the condition may name, and the channels and pools `present(...)` may ask about."""
        self.states = frozenset(states)
        self.targets = frozenset(targets)
        self.words.setStringList(
            [*KEYWORDS, *sorted(self.states), *(f"present({target})" for target in sorted(self.targets))]
        )
        self._highlight()

    def problem(self) -> tuple[int, int, str] | None:
        """What is wrong with the text: where (start, length) and what, None for nothing (also for an empty one)."""
        text = self.text()
        if not text.strip():
            return None
        try:
            parse(text)
        except ExpressionError as error:
            # at the end of the text: the last word is where it went wrong
            position = min(error.position, max(0, len(text.rstrip()) - 1))
            for match in _WORD.finditer(text):
                if match.start() <= position < match.end():
                    return match.start(), match.end() - match.start(), error.message
            return position, 1, error.message
        for word, start, kind in _tokens(text):
            if kind == "name" and word not in self.states:
                return start, len(word), f"There is no state or mode {word}."
            if kind == "target" and word not in self.targets:
                return start, len(word), f"There is no channel or pool {word}."
        return None

    def _highlight(self) -> None:
        """Gives each word the colour of what it is, and underlines the mistake."""
        colors = current_colors()
        spans: list[tuple[int, int, QTextCharFormat]] = []
        for word, start, kind in _tokens(self.text()):
            look = QTextCharFormat()
            if kind == "keyword":
                look.setForeground(QColor(colors.text_muted))
                look.setFontWeight(QFont.Weight.Bold)
            elif kind == "target":
                look.setForeground(QColor(colors.channel))
            elif kind == "name":
                look.setForeground(QColor(colors.state))
            else:
                continue
            spans.append((start, len(word), look))
        problem = self.problem()
        if problem is not None:
            start, length, _ = problem
            wrong = QTextCharFormat()
            wrong.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            wrong.setUnderlineColor(QColor(colors.error))
            wrong.setForeground(QColor(colors.error))
            spans.append((start, length, wrong))
        self.setToolTip(
            problem[2] if problem else "States and modes with `and`, `or`, `not`, parentheses and `present`"
        )
        cursor = self.cursorPosition()
        attributes = [
            QInputMethodEvent.Attribute(
                QInputMethodEvent.AttributeType.TextFormat, start - cursor, length, QTextFormat(look)
            )
            for start, length, look in spans
        ]
        # the only way to give parts of a QLineEdit their own format: an input method event without text (a
        # QTextFormat: Qt ignores a QTextCharFormat there)
        QCoreApplication.sendEvent(self, QInputMethodEvent("", attributes))

    def _partial(self) -> str:
        match = _PARTIAL.search(self.text()[: self.cursorPosition()])
        return match.group() if match else ""

    def _offer(self, always: bool) -> None:
        """Offers the words that start like the one being typed (all of them with `always`)."""
        partial = self._partial()
        popup = self.completer_.popup()
        assert popup is not None
        if not partial and not always:
            popup.hide()
            return
        self.completer_.setCompletionPrefix(partial)
        if self.completer_.completionCount() == 0 or (
            self.completer_.completionCount() == 1 and self.completer_.currentCompletion() == partial
        ):
            popup.hide()
            return
        popup.setCurrentIndex(self.completer_.completionModel().index(0, 0))  # pyright: ignore[reportOptionalMemberAccess]
        rect = self.cursorRect()
        rect.setWidth(max(self.width() // 2, 200))
        self.completer_.complete(rect)

    def _complete(self, word: str) -> None:
        """Puts `word` in place of the one being typed."""
        partial = len(self._partial())
        # selected and typed over, not set: Ctrl+Z takes it back
        self.setSelection(self.cursorPosition() - partial, partial)
        self.insert(word)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        assert a0 is not None
        popup = self.completer_.popup()
        if (
            popup is not None
            and popup.isVisible()
            and a0.key()
            in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Tab,
                Qt.Key.Key_Escape,
            )
        ):
            # the list takes these: Enter and Tab pick, Esc closes it
            a0.ignore()
            return
        if a0.key() == Qt.Key.Key_Space and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._offer(True)
            return
        super().keyPressEvent(a0)

    def changeEvent(self, a0: QEvent | None) -> None:
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.StyleChange:
            # another theme: the colours of the words follow
            self._highlight()


def _tokens(text: str) -> list[tuple[str, int, str]]:
    """The words of `text` with where they start and what they are: keyword, name, target or symbol."""
    tokens: list[tuple[str, int, str]] = []
    for match in _WORD.finditer(text):
        word = match.group()
        if word in "()":
            kind = "symbol"
        elif word in KEYWORDS:
            kind = "keyword"
        elif len(tokens) >= 2 and tokens[-1][0] == "(" and tokens[-2][0] == "present":
            kind = "target"
        else:
            kind = "name"
        tokens.append((word, match.start(), kind))
    return tokens
