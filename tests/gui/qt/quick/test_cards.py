"""
The slot cards in Qt Quick (a prototype): their rows by key, the model that changes them row by row, and the page
that shows them with `XTOUCH_QML_CARDS=1`.
"""

from typing import Any

import pytest
from PyQt6.QtCore import QModelIndex
from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface

from tests.support.gui import MakeWindow
from xtouch_daemon.gui.domain.slot_stacks import rows
from xtouch_daemon.gui.qt.quick.cards import DATA, KEY, RowsModel, card_rows, enabled

VALUES: dict[str, Any] = {
    "channel": {"out": {"type": "output"}, "voip": {"type": "voip"}},
    "slots": {"1": ["voip if present", "out", "-"]},
}


@pytest.fixture(autouse=True)
def software() -> None:
    # offscreen there is no OpenGL
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)


def keys(model: RowsModel) -> list[str]:
    return [model.data(model.index(row), KEY) for row in range(model.rowCount())]


def test_a_row_keeps_its_key_while_its_state_changes():
    shown = card_rows(rows(VALUES, 1), 0, {}, VALUES, False, None)
    passed = card_rows(rows(VALUES, 1), 1, {0: "voip is absent"}, VALUES, False, None)
    assert [key for key, _ in shown] == [key for key, _ in passed]
    assert (shown[0][1]["state"], passed[0][1]["state"]) == ("shown", "passed")
    assert passed[0][1]["reason"] == "voip is absent"
    # `-` at the end: no dark strip of its own
    assert len(shown) == 3


def test_two_candidates_alike_have_keys_of_their_own():
    values = {**VALUES, "slots": {"1": ["out", "out"]}}
    assert len({key for key, _ in card_rows(rows(values, 1), 0, {}, values, False, None)}) == 3


def test_the_model_changes_inserts_and_removes_rows_by_key():
    model = RowsModel()
    changed: list[int] = []
    inserted: list[tuple[int, int]] = []
    removed: list[tuple[int, int]] = []
    model.dataChanged.connect(lambda first, _last, _roles: changed.append(first.row()))
    model.rowsInserted.connect(lambda _parent, first, last: inserted.append((first, last)))
    model.rowsRemoved.connect(lambda _parent, first, last: removed.append((first, last)))
    model.show([("a", {"v": 1}), ("b", {"v": 1}), ("c", {"v": 1})])
    assert inserted == [(0, 2)]

    # b changes in place; a goes, d comes after c
    model.show([("b", {"v": 2}), ("c", {"v": 1}), ("d", {"v": 1})])
    assert keys(model) == ["b", "c", "d"]
    assert removed == [(0, 0)]
    assert inserted[-1] == (2, 2)
    assert changed == [0]
    assert model.data(model.index(0), DATA) == {"v": 2}

    # one row for another at the same place
    model.show([("b", {"v": 2}), ("x", {"v": 1}), ("d", {"v": 1})])
    assert keys(model) == ["b", "x", "d"]
    assert model.rowCount(model.index(0)) == 0
    assert model.data(QModelIndex(), DATA) is None


def test_the_page_shows_the_cards_in_qt_quick(make_window: MakeWindow, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XTOUCH_QML_CARDS", "1")
    assert enabled()
    window = make_window()
    window.show_page("slots")
    page = window.slots_page
    assert page.quick is not None
    assert page.quick.errors() == []
    window.document.set(("slots", "1"), ["out if present", "-"])
    window.editor.edited()
    card = page.quick.cards.cards[0]
    assert card.rows.rowCount() == 2

    # a click on a row in Qt Quick picks it on the page
    page.quick.cards.pick(1, 1)
    assert (page.slot, page.candidate) == (1, 1)
    assert card.current == 1
    assert card.picked
    page.quick.cards.pickSlot(2)
    assert (page.slot, page.candidate) == (2, None)


def test_without_the_variable_the_page_has_its_widget_cards(make_window: MakeWindow):
    assert make_window().slots_page.quick is None
