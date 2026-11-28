"""Simulate and the edit actions of the page Slots in Qt Quick."""

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication

from tests.gui.quick.slots_helpers import model_rows, page, polish, press, snapshot, tell
from tests.support.quick import Ui


def test_simulate_starts_from_reality_and_shows_what_if(ui: Ui):
    slots = page(ui)
    twins: list[Any] = []
    slots.simulated.connect(lambda: twins.append(slots.what_if))
    tell(ui, snapshot((0, 1, None)))
    assert not slots.simulating
    slots.toggleSimulate(True)
    assert slots.simulating
    assert slots.what_if is not None
    assert twins
    titles = [(group.title, group.shown) for group in slots.whatIfGroups]
    assert titles
    # a state turned on in the what-if changes the frame the cards show
    states = [row for group in slots.whatIfGroups for _, row in group.items.rows]
    assert states
    slots.toggleSimulate(False)
    assert not slots.simulating
    assert twins[-1] is None


def test_what_if_toggles_modes_and_counts(ui: Ui):
    slots = page(ui)
    tell(ui, snapshot((0, 1, None)))
    slots.toggleSimulate(True)
    start = slots.what_if
    slots.whatIfToggle("call", True)
    assert slots.what_if is not start
    assert slots.what_if is not None
    slots.whatIfMode("default")
    assert slots.what_if.mode == "default"
    slots.whatIfCount("apps", 2)
    assert slots.what_if is not None


def test_escape_ends_simulate_and_the_bar_follows(ui: Ui):
    slots = page(ui)
    tell(ui, snapshot((0, 1, None)))
    polish(ui)
    press(ui, "simulate")
    assert slots.simulating
    assert ui.shows("what_if_panel")
    ui.key(Qt.Key.Key_Escape)
    assert not slots.simulating
    assert ui.item("simulate").property("checked") is False


def test_simulating_leaves_the_focus_and_the_scroll_alone(ui: Ui):
    slots = page(ui)
    tell(ui, snapshot((0, 1, None)))
    ui.window.resize(1000, 300)
    polish(ui)
    cards = ui.item("cards")
    cards.setProperty("contentY", 120)
    slots.toggleSimulate(True)
    polish(ui)
    assert cards.property("contentY") == 120
    slots.whatIfToggle("call", True)
    polish(ui)
    assert cards.property("contentY") == 120


def test_the_edit_actions_work_on_the_candidate_in_the_focused_card(ui: Ui):
    slots = page(ui)
    doc = ui.app.editor.document
    doc.set(("slots", "3"), ["a", "b if call"])
    ui.app.editor.edited()
    polish(ui)
    slots.pickRow(3, 0)
    ui.focus("list_3")
    slots.edit("copy")
    assert QGuiApplication.clipboard().text() == '"a"'  # pyright: ignore[reportOptionalMemberAccess]
    slots.edit("duplicate")
    assert doc.get(("slots", "3")) == ["a", "a", "b if call"]
    slots.edit("cut")
    assert doc.get(("slots", "3")) == ["a", "b if call"]
    slots.edit("paste")
    assert len(doc.get(("slots", "3"))) == 3  # pyright: ignore[reportArgumentType]
    slots.edit("remove")
    assert len(doc.get(("slots", "3"))) == 2  # pyright: ignore[reportArgumentType]
    rows = model_rows(slots.cards[2].model)
    assert rows
