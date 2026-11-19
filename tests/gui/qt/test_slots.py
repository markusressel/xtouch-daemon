"""
The slots on the page Device: the state bar, a card per slot, the inspector, and editing the stacks.
"""

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QComboBox, QFrame, QPushButton, QToolButton
from PyQt6.QtWidgets import QLabel as QLabelType
from pytestqt.qtbot import QtBot

from tests.support.gui import click, pill, plain
from xtouch_daemon.gui.qt.pages.slot_cards import CandidateRow, StackList
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, SlotsState, SlotView, Snapshot, StateView


def panel(window: MainWindow) -> SlotsPanel:
    return window.slots_page


def texts(stack: StackList) -> list[str]:
    """The text of each candidate: ▶ on the one the device shows, its number, its rule, its chips."""
    found: list[str] = []
    for index in range(stack.count()):
        item = stack.item(index)
        assert item is not None
        widget = stack.itemWidget(item)
        if widget is None:
            found.append(item.text())
            continue
        text = " ".join(child.text() for child in widget.findChildren(QLabelType) if child.text())
        shown = isinstance(widget, CandidateRow) and widget.state == "shown"
        found.append(f"▶ {text}" if shown else text)
    return found


def why(page: SlotsPanel) -> list[str]:
    """The lines of the box that says why the slot shows what it shows."""
    rows = page.why_rows
    found: list[str] = []
    for index in range(rows.count()):
        item = rows.itemAt(index)
        assert item is not None
        if isinstance(widget := item.widget(), QLabelType):
            found.append(widget.text())
    return found


def popover_buttons(window: MainWindow) -> dict[str, QPushButton]:
    """The buttons of the popover opened last (one that closed is only deleted later)."""
    popover = [frame for frame in window.findChildren(QFrame) if frame.property("role") == "popup"][-1]
    return {button.text(): button for button in popover.findChildren(QPushButton)}


def snapshot(candidates: tuple[int | None, ...], pick: str | None = None, call: bool = True) -> Snapshot:
    views = tuple(
        SlotView(slot, candidate, None, None, None, (f"shows {candidate}",))
        for slot, candidate in enumerate(candidates, 1)
    )
    states = (
        StateView("call", call, False, None, "mumble runs" if call else None, "auto"),
        StateView("gaming", pick == "gaming", True, None, None, "auto"),
    )
    slots = SlotsState("default", pick, views, states, {})
    return Snapshot("x", True, sound_server=True, mqtt=None, strips=(), slots=slots)


def test_the_cards_show_the_stacks(window: MainWindow):
    page = panel(window)
    assert texts(page.lists[0]) == ["1 always → out"]
    assert texts(page.lists[1]) == ["1 when call → browser", "2 when app or person without a slot → auto"]
    assert texts(page.lists[2]) == ["auto (no entry)"]
    assert page.title.text() == "Slot 1"
    assert plain(page.controls.text()).startswith("Pick a candidate to edit it.")

    window.device_view.select(1)
    assert (page.slot, page.candidate) == (2, 0)
    assert page.title.text() == "Slot 2"
    assert page.show_box.currentText() == "browser"
    assert page.when_edit.text() == "call"
    assert plain(page.channel.text()) == "Channel browser (Applications). Used nowhere else."
    assert not page.channel_button.isHidden()
    click_channel = page.channel_button
    click_channel.click()
    assert window.current_page == "channels"

    page.lists[1].setCurrentRow(1)
    assert page.candidate == 1
    assert plain(page.channel.text()).startswith("Pool auto: the people (from the right) and the applications")
    assert "encoder" in [option_row.option.name for option_row in page.place_rows]
    assert page.channel_button.isHidden()


def test_the_device_shows_which_candidate_and_the_states(window: MainWindow):
    page = panel(window)
    sent: list[Request] = []
    page.request = lambda request: sent.append(request) is None
    live = snapshot((0, 1, None))
    page.snapshot = lambda: live
    page.show_live(live)
    assert texts(page.lists[1]) == ["1 when call → browser", "▶ 2 when app or person without a slot → auto"]
    assert pill(page.state_buttons["call"]) == "● call"
    page.show_live(live)
    window.device_view.select(1)
    assert page.candidate == 1
    assert why(page) == ["Now", "→", "1"]
    page.lists[1].setCurrentRow(0)
    assert plain(page.channel.text()).endswith("On no slot, and no slot asks for it.")

    # a state opens a popover: its value, the override, a simulation of it the other way
    page.state_buttons["call"].click()
    assert list(popover_buttons(window)) == ["Override: on", "Override: off", "Simulate it off"]
    popover_buttons(window)["Override: off"].click()
    assert sent == [SetOverride("call", "off")]

    window.document.set(("state", "gaming"), {"mode": True, "processes": ["steam"]})
    window.editor.edited()
    page.state_buttons["gaming"].click()
    assert list(popover_buttons(window)) == ["Pick gaming", "Simulate gaming as the mode"]
    popover_buttons(window)["Pick gaming"].click()
    assert sent[1:] == [SetMode("gaming")]
    live = snapshot((0, 1, None), pick="gaming", call=False)
    page.show_live(live)
    assert pill(page.state_buttons["gaming"]) == "● gaming (picked)"
    assert pill(page.state_buttons["call"]) == "○ call"
    page.snapshot = lambda: None
    page.show_live(None)
    assert pill(page.state_buttons["call"]) == "call"
    assert page.why.isHidden()


def test_candidates_are_added_moved_changed_and_removed(qtbot: QtBot, window: MainWindow):
    page = panel(window)
    click(qtbot, page.card_frames[2].findChildren(QToolButton)[0])
    assert window.document.get(("slots", "3")) == "auto"
    assert (page.slot, page.candidate) == (3, 0)

    page.show_box.setCurrentText("out")
    page.show_box.activated.emit(0)
    assert window.document.get(("slots", "3")) == "out"
    page.when_edit.setText("call")
    page.when_edit.editingFinished.emit()
    assert window.document.get(("slots", "3")) == "out if call"
    page.when_edit.editingFinished.emit()

    page.add(3)
    assert window.document.get(("slots", "3")) == ["out if call", "auto"]
    stack = page.lists[2]
    stack.setFocus()
    qtbot.keyClick(stack, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert window.document.get(("slots", "3")) == ["auto", "out if call"]
    assert page.candidate == 0
    qtbot.keyClick(page.lists[2], Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(page.lists[2], Qt.Key.Key_Down)
    assert window.document.get(("slots", "3")) == ["auto", "out if call"]
    assert page.candidate == 1
    page.lists[2].setCurrentRow(0)

    # an option of the place, kept with the candidate, and dropped when it shows something that has no use for it
    (encoder,) = [option_row for option_row in page.place_rows if option_row.option.name == "encoder"]
    encoder.findChild(QComboBox).setCurrentIndex(1)  # pyright: ignore[reportOptionalMemberAccess]
    (first, _) = window.document.get(("slots", "3"))
    assert first["show"] == "auto"
    assert "encoder" in first
    page.show_box.setCurrentText("out")
    page.show_box.lineEdit().editingFinished.emit()  # pyright: ignore[reportOptionalMemberAccess]
    assert window.document.get(("slots", "3")) == ["out", "out if call"]

    page.show_box.setCurrentText(" ")
    page.show_box.activated.emit(0)
    assert window.document.get(("slots", "3")) == ["out", "out if call"]
    page.show_box.setCurrentText("-")
    page.show_box.activated.emit(0)
    assert page.channel.text() == "Nothing: the strip is dark."
    assert page.place_rows == []
    page.show_box.setCurrentText("browser")
    page.show_box.activated.emit(0)
    (name,) = [option_row for option_row in page.place_rows if option_row.option.name == "label"]
    name.line.setText("Apps")
    name.line.textEdited.emit("Apps")
    assert window.document.get(("slots", "3", 0)) == {"show": "browser", "label": "Apps"}
    name.reset.click()
    assert window.document.get(("slots", "3")) == ["browser", "out if call"]
    page.show_box.setCurrentText("out")
    page.show_box.activated.emit(0)

    # a drop writes the order the list has now
    stack = page.lists[2]
    mime = stack.model().mimeData([stack.model().index(0, 0)])  # pyright: ignore[reportOptionalMemberAccess]
    drop = QDropEvent(
        QPointF(5, 5), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    stack.dropEvent(drop)
    assert window.document.get(("slots", "3")) == ["out", "out if call"]
    stack.currentRowChanged.emit(-1)

    page.lists[2].reordered.emit([1, 0], 0)
    assert window.document.get(("slots", "3")) == ["out if call", "out"]
    page.remove(3)
    page.remove(3)
    assert window.document.get(("slots", "3")) is None
    assert page.candidate is None
    page.remove(3)
    page.remove(4)
    # undo takes the candidate the inspector shows away
    page.add(3)
    page.add(3)
    window.undo()
    assert page.candidate == 0


def test_problems_show_on_the_card_and_in_the_inspector(window: MainWindow):
    page = panel(window)
    window.document.set(("slots", "2"), ["browser if nonsense", "auto"])
    window.editor.edited()
    assert page.card_frames[1].property("problem") is True
    assert page.card_frames[1].toolTip() != ""
    (action,) = window.problems_menu.actions()
    action.trigger()
    assert window.current_page == "slots"
    assert page.slot == 2
    page.lists[1].setCurrentRow(0)
    assert page.problem.text() != ""
    page.lists[0].setCurrentRow(0)
    assert page.slot == 1
    # a slot the device does not have
    window.document.set(("slots", "9"), "out")
    window.editor.edited()
    window.show_page("states")
    (action,) = [action for action in window.problems_menu.actions() if "1 to 8" in action.text()]
    action.trigger()
    assert window.current_page == "slots"


def test_controls_of_a_slot_are_listed(window: MainWindow):
    window.document.set(("controls", "1"), {"select": "toggle:call"})
    window.editor.edited()
    assert plain(panel(window).controls.text()) == "[controls] claims parts of slot 1: select: toggle:call."


def test_simulate_shows_what_the_slots_would_show(qtbot: QtBot, window: MainWindow):
    page = panel(window)
    device = window.device_view
    window.document.set(("state", "gaming"), {"mode": True, "processes": ["steam"]})
    window.document.set(("slots", "3"), ["browser if gaming", "-"])
    window.editor.edited()
    sent: list[Request] = []
    page.request = lambda request: sent.append(request) is None

    page.simulate_button.click()
    assert page.what_if is not None
    assert device.preview.simulating
    assert page.state_bar_row.isHidden()
    assert not page.what_if_row.isHidden()
    # no state is on and nothing waits for a slot: auto has nothing, so the strip is dark
    assert texts(page.lists[1]) == [
        "1 when call → browser ✗ call is off",
        "2 when app or person without a slot → auto ✗ no app or person without a slot",
        "▶ nothing to show: the strip is dark",
    ]
    assert texts(page.lists[2]) == ["1 when gaming → browser ✗ gaming is off", "▶ 2 otherwise → -"]
    # no daemon: the drawing is dark (only the device shows strips), the cards simulate
    assert device.preview.strips[0].face.look.printed == ""
    assert device.preview.strips[2].face.state.color == "off"

    # the bar of what-ifs: the mode, the states, the presence the stacks ask about
    (mode,) = page.what_if_row.findChildren(QComboBox)
    mode.setCurrentText("gaming")
    assert texts(page.lists[2]) == ["▶ 1 when gaming → browser", "2 otherwise → -"]
    toggles = {toggle.text(): toggle for toggle in page.what_if_row.findChildren(QPushButton)}
    toggles["call"].click()
    assert texts(page.lists[1])[0] == "▶ 1 when call → browser"
    assert why(page)[0] == "What if"
    assert sent == []

    # Esc ends it
    device.preview.strips[0].setFocus()
    qtbot.keyClick(device.preview.strips[0], Qt.Key.Key_Escape)
    assert page.what_if is None
    assert not device.preview.simulating
    assert not page.simulate_button.isChecked()

    # a file with problems has nothing to simulate
    page.simulate_button.click()
    window.document.set(("slots", "3"), "nothing")
    window.editor.edited()
    assert page.what_if is None
    assert not page.simulate_button.isEnabled()
