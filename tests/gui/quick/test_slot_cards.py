"""The cards of the page Slots in Qt Quick: keyed rows, moving them, the wheel, the keyboard."""

from typing import Any

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QWheelEvent

from tests.gui.quick.slots_helpers import click_row, model_rows, page, polish, press, snapshot, tell, texts
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.pages.slots_cards import MovableRows


def keys(model: MovableRows) -> list[str]:
    return [key for key, _ in model.rows]


def test_rows_move_by_key_without_rebuilding():
    model = MovableRows()
    model.show([("a", {"v": 1}), ("b", {"v": 2}), ("c", {"v": 3})])
    moved: list[tuple[int, int]] = []
    model.rowsMoved.connect(lambda _p, first, _l, _d, row: moved.append((first, row)))
    assert model.move(0, 2)
    assert keys(model) == ["b", "c", "a"]
    assert moved == [(0, 3)]
    assert not model.move(1, 1)
    assert not model.move(0, 3)
    assert not model.move(-1, 0)
    assert model.move(2, 0)
    assert keys(model) == ["a", "b", "c"]


def test_a_state_change_updates_rows_in_place(ui: Ui):
    slots = page(ui)
    tell(ui, snapshot((0, 1, None)))
    model = slots.cards[1].model
    before = keys(model)
    changes: list[Any] = []
    model.rowsInserted.connect(lambda *args: changes.append(args))
    model.rowsRemoved.connect(lambda *args: changes.append(args))
    tell(ui, snapshot((1, 0, None), pick="gaming"))
    assert keys(model) == before
    assert changes == []


def test_the_rail_ends_in_the_end_row(ui: Ui):
    ui.app.editor.document.set(("slots", "3"), ["browser if call"])
    ui.app.editor.edited()
    ui.settle()
    rows = model_rows(page(ui).cards[2].model)
    assert rows[-1]["end"]
    assert [row["last"] for row in rows].count(True) == 1


def test_the_wheel_scrolls_at_the_speed_of_the_desktop(ui: Ui):
    ui.window.resize(1000, 300)
    polish(ui)
    scroll = ui.item("cards")
    notch = QGuiApplication.styleHints().wheelScrollLines() * 20  # pyright: ignore[reportOptionalMemberAccess]
    assert scroll.property("notch") == notch
    assert scroll.property("maxY") > 3 * notch
    center = ui.center(scroll)
    for _ in range(2):
        event = QWheelEvent(
            QPointF(center),
            QPointF(ui.window.mapToGlobal(center)),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QGuiApplication.sendEvent(ui.window, event)
    ui.settle()
    assert scroll.property("contentY") == 2 * notch


def test_ctrl_down_and_up_move_the_candidate_picked(ui: Ui):
    slots = page(ui)
    doc = ui.app.editor.document
    doc.set(("slots", "3"), ["a", "b if call", "c"])
    ui.app.editor.edited()
    polish(ui)
    click_row(ui, 3, 0)
    ui.focus("list_3")
    ui.key(Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert doc.get(("slots", "3")) == ["b if call", "a", "c"]
    assert slots.candidate == 1
    ui.key(Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert doc.get(("slots", "3")) == ["a", "b if call", "c"]
    assert slots.candidate == 0
    ui.key(Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert slots.candidate == 0


def test_a_drag_reorders_the_candidates(ui: Ui):
    doc = ui.app.editor.document
    doc.set(("slots", "3"), ["a", "b", "c"])
    ui.app.editor.edited()
    polish(ui)
    start = ui.center(ui.item("row_3_0"))
    end = ui.center(ui.item("row_3_2")) + QPoint(0, 10)
    ui.qtbot.mousePress(ui.window, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 11):
        ui.qtbot.mouseMove(ui.window, start + (end - start) * step / 10)
        ui.settle()
    ui.qtbot.mouseRelease(ui.window, Qt.MouseButton.LeftButton, pos=end)
    ui.settle()
    assert doc.get(("slots", "3")) == ["b", "c", "a"]
    assert texts(ui, 3)[2].endswith("a")


def test_a_click_below_the_cards_picks_nothing(ui: Ui):
    slots = page(ui)
    press(ui, "row_1_0")
    assert slots.slot == 1
    ui.window.resize(1000, 4000)
    polish(ui)
    press(ui, "below_cards")
    assert slots.slot == 0
