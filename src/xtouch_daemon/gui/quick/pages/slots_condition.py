"""
A field for a condition (`gaming and not present`) in QML: the words in the colors of what they are, mistakes
underlined, and the words it can take offered while typing. `ConditionHelper` works on the `TextEdit` of
`ConditionField.qml`: it highlights its document, says what is wrong and which words fit what is typed.
"""

import re
from collections.abc import Iterable
from typing import Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PyQt6.QtQml import qmlRegisterType
from PyQt6.QtQuick import QQuickTextDocument

from xtouch_daemon.slots.expressions import ExpressionError, parse

KEYWORDS = ("and", "or", "not", "present")
_WORD = re.compile(r"[a-z0-9_]+|[()]")
_PARTIAL = re.compile(r"[a-z0-9_(]*$")
"""The word being typed, up to the cursor: `pres`, `present(ga`."""
HELP = "States and modes with `and`, `or`, `not`, parentheses and `present`"
URI = "XTouch.Slots"
"""The module QML imports the types of this page from (`import XTouch.Slots`)."""


def tokens(text: str) -> list[tuple[str, int, str]]:
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


def problem_of(
    text: str, states: frozenset[str], targets: frozenset[str], present: bool
) -> tuple[int, int, str] | None:
    """What is wrong with `text`: where (start, length) and what, None for nothing (also for an empty text)."""
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
    for word, start, kind in tokens(text):
        if word == "present" and not present:
            return start, len(word), "present is only for candidates of slots."
        if kind == "name" and word not in states:
            return start, len(word), f"There is no state or mode {word}."
        if kind == "target" and word not in targets:
            return start, len(word), f"There is no channel or pool {word}."
    return None


def words_of(states: Iterable[str], targets: Iterable[str], present: bool) -> list[str]:
    """All the words a condition can take: keywords, states and modes, and `present(...)` of each target."""
    return [
        *(word for word in KEYWORDS if present or word != "present"),
        *sorted(states),
        *(f"present({target})" for target in sorted(targets)),
    ]


def partial_of(text: str, cursor: int) -> str:
    """The word being typed, up to `cursor`."""
    match = _PARTIAL.search(text[:cursor])
    return match.group() if match else ""


def offers(words: Iterable[str], partial: str, always: bool) -> list[str]:
    """The words that start like `partial` (all of them with `always`); none when `partial` is all of the word."""
    if not partial and not always:
        return []
    matching = [word for word in words if word.lower().startswith(partial.lower())]
    return [] if not matching or matching == [partial] else matching


class _Highlighter(QSyntaxHighlighter):
    def __init__(self, helper: ConditionHelper, document: QTextDocument) -> None:
        super().__init__(document)
        self.helper = helper

    def highlightBlock(self, text: str | None) -> None:
        text = text or ""
        for word, start, kind in tokens(text):
            look = QTextCharFormat()
            if kind == "keyword":
                look.setForeground(self.helper.palette("text_muted"))
                look.setFontWeight(QFont.Weight.Bold)
            elif kind == "target":
                look.setForeground(self.helper.palette("channel"))
            elif kind == "name":
                look.setForeground(self.helper.palette("state"))
            else:
                continue
            self.setFormat(start, len(word), look)
        problem = self.helper.problem_at(text)
        if problem is not None:
            start, length, _ = problem
            wrong = QTextCharFormat()
            wrong.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            wrong.setUnderlineColor(self.helper.palette("error"))
            wrong.setForeground(self.helper.palette("error"))
            self.setFormat(start, length, wrong)


class ConditionHelper(QObject):
    """
    The brain of a `ConditionField`: set its `document` (the `textDocument` of the `TextEdit`), the `states` and
    `targets` it may name, its `colors` (`Theme.colors`) and whether `present` is allowed.
    """

    changed = pyqtSignal(arguments=[])
    problemChanged = pyqtSignal(arguments=[])

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self._states: frozenset[str] = frozenset()
        self._targets: frozenset[str] = frozenset()
        self._present = True
        self._colors: dict[str, Any] = {}
        self._problem = ""
        self._highlighter: _Highlighter | None = None
        self._document: QTextDocument | None = None

    # -- what QML sets --------------------------------------------------------------------------------------------

    @pyqtProperty(QQuickTextDocument)  # pyright: ignore[reportArgumentType]
    def document(self) -> QQuickTextDocument | None:  # pyright: ignore[reportRedeclaration]
        return None

    @document.setter
    def document(self, document: QQuickTextDocument) -> None:
        inner = document.textDocument()
        assert inner is not None
        self._document = inner
        self._highlighter = _Highlighter(self, inner)
        inner.contentsChanged.connect(self._read)

    @pyqtProperty(bool, notify=changed)
    def present(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._present

    @present.setter
    def present(self, present: bool) -> None:
        self._present = present
        self._changed()

    @pyqtProperty("QStringList", notify=changed)
    def states(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return sorted(self._states)

    @states.setter
    def states(self, states: list[str]) -> None:
        self._states = frozenset(states)
        self._changed()

    @pyqtProperty("QStringList", notify=changed)
    def targets(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return sorted(self._targets)

    @targets.setter
    def targets(self, targets: list[str]) -> None:
        self._targets = frozenset(targets)
        self._changed()

    @pyqtProperty("QVariantMap", notify=changed)
    def colors(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        return self._colors

    @colors.setter
    def colors(self, colors: dict[str, Any]) -> None:
        self._colors = dict(colors)
        self._changed()

    # -- what it knows --------------------------------------------------------------------------------------------

    @pyqtProperty(str, notify=problemChanged)
    def problem(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What is wrong with the text, "" for nothing."""
        return self._problem

    @pyqtProperty("QStringList", notify=changed)
    def words(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return words_of(self._states, self._targets, self._present)

    def palette(self, name: str) -> QColor:
        return QColor(self._colors.get(name, "#808080"))

    def problem_at(self, text: str) -> tuple[int, int, str] | None:
        return problem_of(text, self._states, self._targets, self._present)

    def _changed(self) -> None:
        self.changed.emit()
        if self._highlighter is not None:
            self._highlighter.rehighlight()
        self._read()

    def _read(self) -> None:
        text = self._document.toPlainText() if self._document is not None else ""
        found = problem_of(text, self._states, self._targets, self._present)
        message = found[2] if found else ""
        if message != self._problem:
            self._problem = message
            self.problemChanged.emit()

    @pyqtSlot(str, int, bool, result="QStringList")
    def offer(self, text: str, cursor: int, always: bool) -> list[str]:
        """The words to offer for what is typed before `cursor`."""
        return offers(self.words, partial_of(text, cursor), always)

    @pyqtSlot(str, int, result="int")
    def partialLength(self, text: str, cursor: int) -> int:
        """How many characters before `cursor` are the word being typed (a completion replaces them)."""
        return len(partial_of(text, cursor))


def register() -> None:
    """Makes `ConditionHelper` known to QML as `XTouch.Slots`."""
    qmlRegisterType(ConditionHelper, URI, 1, 0, "ConditionHelper")
