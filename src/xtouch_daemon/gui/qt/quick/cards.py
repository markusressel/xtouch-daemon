"""
A prototype: the slot cards of the page Slots in Qt Quick (`Cards.qml`), to try how it moves. The widget cards stay
underneath (hidden): they keep what is picked and do the editing; this only shows. `XTOUCH_QML_CARDS=1` turns it on.

Each card has a list model (`RowsModel`) that changes row by row: a row that stays is changed in place (its values
animate in QML), a row that comes is inserted and one that goes is removed (QML animates both, and the rows around
move along).
"""

import difflib
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QUrl,
    pyqtProperty,  # pyright: ignore[reportUnknownVariableType]
    pyqtSignal,
    pyqtSlot,  # pyright: ignore[reportUnknownVariableType]
)
from PyQt6.QtGui import QColor
from PyQt6.QtQuickWidgets import QQuickWidget

from xtouch_daemon.gui.domain.slot_stacks import (
    ALWAYS,
    EMPTY,
    Row,
    ends_dark,
    free_text,
    free_words,
    is_pool,
    lcd_colors,
    readable,
    row_state,
)
from xtouch_daemon.gui.qt.pages.slot_cards import NODE
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import LCD_COLORS, TINT_ALPHA, Motion, Radius, Space
from xtouch_daemon.slots.model import AUTO

ENABLED = "XTOUCH_QML_CARDS"
"""The environment variable that turns the cards in Qt Quick on."""
QML = Path(__file__).with_name("Cards.qml")


def enabled() -> bool:
    return os.environ.get(ENABLED, "") not in ("", "0")


def option_text(value: Any) -> str:
    """A value of an option as in the file, without quotes: `white`, `true`, `[a, b]`."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(option_text(item) for item in value) + "]"  # pyright: ignore[reportUnknownVariableType]
    return str(value)


def candidate_data(
    candidate: Row,
    state: str,
    index: int,
    count: int,
    values: Mapping[str, Any],
    reason: str,
    member: tuple[str, str] | None,
) -> dict[str, Any]:
    """What a row of a candidate shows, as `candidate_rule` of the widget cards does, for QML."""
    chips: list[dict[str, Any]] = []
    if candidate.chips == (ALWAYS,) and is_pool(values, candidate.show):
        lead = "when"
        chips.append(
            {"text": free_words(values, candidate.show), "kind": "presence", "tip": free_text(values, candidate.show)}
        )
    elif candidate.chips == (ALWAYS,):
        lead = "otherwise" if index == count - 1 and count > 1 else ALWAYS
    else:
        lead = "when"
        for position, part in enumerate(candidate.chips):
            words, presence = readable(part, candidate.show, values)
            chips.append({"text": words, "kind": "presence" if presence else "state", "or": position > 0, "tip": part})
    colors = [color for color, _ in lcd_colors(values, candidate) if color in LCD_COLORS]
    rest = {
        name: value
        for name, value in candidate.options.items()
        if name != "color" or not (isinstance(value, str) and value in LCD_COLORS)
    }
    return {
        "number": str(index + 1),
        "lead": lead,
        "chips": chips,
        "show": candidate.show if member is None else f"{candidate.show} · {member[0]}",
        "nothing": candidate.show == EMPTY,
        "swatches": [LCD_COLORS[color] for color in colors],
        "options": ", ".join(f"{name} = {option_text(value)}" for name, value in rest.items()),
        "reason": reason,
        "state": state,
        "first": index == 0,
        "last": index == count - 1,
        "end": False,
    }


def end_data(index: int, count: int, dark: bool, state: str) -> dict[str, Any]:
    """The dark strip at the end of the rail."""
    return {
        "number": "",
        "lead": "",
        "chips": [],
        "show": "nothing to show: the strip is dark" if dark else "nothing to show: the strip goes dark",
        "nothing": True,
        "swatches": [LCD_COLORS["off"]],
        "options": "",
        "reason": "",
        "state": state,
        "first": index == 0,
        "last": True,
        "end": True,
    }


def card_rows(
    candidates: list[Row],
    shown: int | None,
    why: Mapping[int, str],
    values: Mapping[str, Any],
    dark: bool,
    member: tuple[str, str] | None,
) -> list[tuple[str, dict[str, Any]]]:
    """
    The rows of a card, each with its key: the candidate as the file has it (and how often it came before, for two
    alike), so a row keeps its key while only its state, its reason or what it hands out changes.
    """
    count = len(candidates) + ends_dark(candidates)
    result: list[tuple[str, dict[str, Any]]] = []
    seen: dict[str, int] = {}
    for index, candidate in enumerate(candidates):
        state = row_state(index, shown, dark)
        identity = repr(candidate.entry())
        seen[identity] = seen.get(identity, 0) + 1
        data = candidate_data(
            candidate, state, index, count, values, why.get(index, ""), member if state == "shown" else None
        )
        result.append((f"{identity}#{seen[identity]}", data))
    if ends_dark(candidates):
        state = "shown" if dark else "" if shown is None else "unreached"
        result.append(("end", end_data(len(candidates), count, dark, state)))
    if not result:
        result.append(
            (
                "auto",
                {
                    **end_data(0, 1, False, ""),
                    "show": f"{AUTO} (no entry)",
                    "swatches": [],
                    "end": False,
                },
            )
        )
    return result


NO_PARENT = QModelIndex()
KEY = Qt.ItemDataRole.UserRole + 1
DATA = Qt.ItemDataRole.UserRole + 2


class RowsModel(QAbstractListModel):
    """The rows of one card, changed row by row (see the module)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rows: list[tuple[str, dict[str, Any]]] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def roleNames(self) -> dict[int, QByteArray]:
        return {KEY: QByteArray(b"key"), DATA: QByteArray(b"row")}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        key, data = self.rows[index.row()]
        if role == KEY:
            return key
        if role == DATA:
            return data
        return None

    def show(self, rows: Sequence[tuple[str, dict[str, Any]]]) -> None:
        """The new rows: by their keys, rows go, come or change in place."""
        old = [key for key, _ in self.rows]
        new = [key for key, _ in rows]
        offset = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
            if tag == "equal":
                for step in range(i2 - i1):
                    at = i1 + offset + step
                    if self.rows[at] != rows[j1 + step]:
                        self.rows[at] = rows[j1 + step]
                        self.dataChanged.emit(self.index(at), self.index(at), [DATA])
                continue
            at = i1 + offset
            if i2 > i1:
                self.beginRemoveRows(QModelIndex(), at, at + i2 - i1 - 1)
                del self.rows[at : at + i2 - i1]
                self.endRemoveRows()
            if j2 > j1:
                self.beginInsertRows(QModelIndex(), at, at + j2 - j1 - 1)
                self.rows[at:at] = list(rows[j1:j2])
                self.endInsertRows()
            offset += (j2 - j1) - (i2 - i1)


class SlotCard(QObject):
    """A card: its slot, its rows, which row is picked and whether the slot is."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, number: int, parent: QObject) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self._number = number
        self._rows = RowsModel(self)
        self._current = -1
        self._picked = False
        self._problem = ""

    @pyqtProperty(int, constant=True)
    def number(self) -> int:  # pyright: ignore[reportRedeclaration]
        return self._number

    @pyqtProperty(QObject, constant=True)
    def rows(self) -> RowsModel:  # pyright: ignore[reportRedeclaration]
        return self._rows

    @pyqtProperty(int, notify=changed)
    def current(self) -> int:  # pyright: ignore[reportRedeclaration]
        return self._current

    @pyqtProperty(bool, notify=changed)
    def picked(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._picked

    @pyqtProperty(str, notify=changed)
    def problem(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._problem

    def show(self, current: int, picked: bool, problem: str) -> None:
        if (current, picked, problem) != (self._current, self._picked, self._problem):
            self._current, self._picked, self._problem = current, picked, problem
            self.changed.emit()


@dataclass(frozen=True)
class CardContents:
    """What `QuickCards.show_card` needs of a card."""

    rows: list[tuple[str, dict[str, Any]]]
    current: int
    picked: bool
    problem: str


class Cards(QObject):
    """The cards for QML, and what a click on them does."""

    def __init__(self, count: int, pick: Callable[[int, int], None], pick_slot: Callable[[int], None]) -> None:
        super().__init__()
        self._cards = [SlotCard(number, self) for number in range(1, count + 1)]
        self._pick = pick
        self._pick_slot = pick_slot

    @pyqtProperty(list, constant=True)
    def cards(self) -> list[SlotCard]:  # pyright: ignore[reportRedeclaration]
        return self._cards

    @pyqtSlot(int, int)
    def pick(self, slot: int, row: int) -> None:
        self._pick(slot, row)

    @pyqtSlot(int)
    def pickSlot(self, slot: int) -> None:
        self._pick_slot(slot)


def theme() -> dict[str, Any]:
    """The colors and sizes of the window, for QML."""
    colors = current_colors()
    names = (
        "surface",
        "raised",
        "sunken",
        "border",
        "control_border",
        "text",
        "text_muted",
        "accent",
        "accent_tint",
        "error",
        "tone_good",
        "state",
        "channel",
        "slot",
        "presence",
    )
    return {
        **{name: getattr(colors, name) for name in names},
        "radius": Radius.LARGE,
        "pill": Radius.PILL,
        "tint": 2 * TINT_ALPHA / 255,
        "node": NODE,
        "xs": Space.XS,
        "s": Space.S,
        "m": Space.M,
        "fade": Motion.FADE if Motion.enabled else 0,
        "resize": Motion.RESIZE if Motion.enabled else 0,
    }


class QuickCards(QQuickWidget):
    """The cards in Qt Quick."""

    def __init__(self, count: int, pick: Callable[[int, int], None], pick_slot: Callable[[int], None]) -> None:
        super().__init__()
        self.cards = Cards(count, pick, pick_slot)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setClearColor(QColor(current_colors().surface))
        context = self.rootContext()
        assert context is not None
        context.setContextProperty("cards", self.cards)
        context.setContextProperty("theme", theme())
        self.setSource(QUrl.fromLocalFile(str(QML)))
        for error in self.errors():
            raise RuntimeError(error.toString())

    def show_card(self, slot: int, contents: CardContents) -> None:
        card = self.cards.cards[slot - 1]
        card.rows.show(contents.rows)
        card.show(contents.current, contents.picked, contents.problem)
