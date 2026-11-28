"""
The slots on the page Device: the state bar, a card per slot, the inspector, and editing the stacks.
"""

import dataclasses

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QFrame, QPushButton, QSpinBox, QToolButton, QWidget
from PyQt6.QtWidgets import QLabel as QLabelType
from pytestqt.qtbot import QtBot

from tests.support.gui import FakeLiveDaemon, MakeWindow, click, pill, plain, strip_state
from tests.support.gui import snapshot as device_snapshot
from xtouch_daemon.gui.domain.live_preview import Place
from xtouch_daemon.gui.domain.simulate import WhatIf
from xtouch_daemon.gui.qt.fields.basics import DOT_ICON
from xtouch_daemon.gui.qt.fields.controls import LcdBadge
from xtouch_daemon.gui.qt.pages.slot_cards import NODE_ICON, CandidateRow, ShowChip, StackList
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.theme import style
from xtouch_daemon.gui.qt.theme.tokens import THEMES, ThemeMode
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import (
    EndPreview,
    Play,
    Request,
    SetMode,
    SetOverride,
    SlotsState,
    SlotView,
    Snapshot,
    StartPreview,
    StateView,
    TwinView,
)
from xtouch_daemon.slots.outcomes import Situation


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
    # each rail ends in the dark strip, always the last option (a channel can be on another slot, a pool empty)
    assert texts(page.lists[0]) == ["1 always → out", "nothing to show: the strip goes dark"]
    assert texts(page.lists[1]) == [
        "1 when call → browser",
        "2 when app or person without a slot → auto",
        "nothing to show: the strip goes dark",
    ]
    assert texts(page.lists[2]) == ["auto (no entry)"]
    # at the start no slot is picked: the overview takes the place of the inspector
    assert page.slot is None
    assert page.right.part is page.overview_scroll
    page.pick_slot(1)
    assert page.right.part is page.inspector_scroll
    assert page.title.text() == "Slot 1"
    assert plain(page.hint.text()).startswith("Pick a candidate to edit it.")

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
    assert page.channel_button.text() == "Edit the pool"
    window.show_page("slots")
    page.channel_button.click()
    assert window.current_page == "channels"
    assert window.channels_page.selection == ("pool", "auto")


def overview_lines(page: SlotsPanel) -> list[QWidget]:
    lines = page.overview_lines
    return [widget for index in range(lines.count()) if (widget := lines.itemAt(index).widget()) is not None]  # pyright: ignore[reportOptionalMemberAccess]


def overview(page: SlotsPanel) -> list[str]:
    """The lines of the overview, as they read."""
    return [" ".join(plain(child.text()) for child in line.findChildren(QLabelType)) for line in overview_lines(page)]


def test_the_overview_has_a_line_for_each_slot(qtbot: QtBot, window: MainWindow):
    page = panel(window)
    window.show_page("slots")
    lines = overview(page)
    assert len(lines) == 8
    assert lines[:3] == ["Slot 1 1 candidate", "Slot 2 2 candidates", "Slot 3 No candidate: auto"]
    # what the daemon tells, and the problems of a slot
    live = snapshot((0, 1, None))
    page.snapshot = lambda: live
    page.show_live(live)
    assert overview(page)[0] == "Slot 1 Shows 0; 1 candidate"
    window.document.set(("controls", "1"), {"select": "nonsense"})
    window.editor.edited()
    assert overview(page)[0].endswith("; 1 problem")
    # a click on a line picks its slot, and the drawing its strip
    click(qtbot, overview_lines(page)[0])
    assert (page.slot, page.candidate) == (1, None)
    assert window.device_view.selected == 0


def test_a_click_picks_a_slot_a_candidate_or_nothing(qtbot: QtBot, window: MainWindow):
    page = panel(window)
    window.show_page("slots")
    # on a card beside its candidates: the slot alone, outlined
    qtbot.mouseClick(
        page.card_frames[2], Qt.MouseButton.LeftButton, pos=page.card_frames[2].rect().topLeft() + QPoint(4, 4)
    )
    assert (page.slot, page.candidate) == (3, None)
    assert page.card_frames[2].property("picked")
    assert window.device_view.preview.strips[2].selected
    # a candidate: its slot too, and the strip follows
    page.lists[1].setCurrentRow(1)
    assert (page.slot, page.candidate) == (2, 1)
    assert not page.card_frames[2].property("picked")
    assert window.device_view.selected == 1
    # below the cards: nothing
    area = page.cards_area
    qtbot.mouseClick(area, Qt.MouseButton.LeftButton, pos=QPoint(area.width() // 2, area.height() - 2))
    assert (page.slot, page.candidate) == (None, None)
    assert all(stack.currentRow() == -1 for stack in page.lists)
    assert window.device_view.selected is None
    assert page.right.part is page.overview_scroll


def test_the_device_shows_which_candidate_and_the_states(window: MainWindow):
    page = panel(window)
    sent: list[Request] = []
    page.request = lambda request: sent.append(request) is None
    live = snapshot((0, 1, None))
    page.snapshot = lambda: live
    page.show_live(live)
    assert texts(page.lists[1]) == [
        "1 when call → browser",
        "▶ 2 when app or person without a slot → auto",
        "nothing to show: the strip goes dark",
    ]
    assert pill(page.state_buttons["call"]) == "● call"
    # the dot at the scale of the screen (1 offscreen): sharp, not drawn at 2 and scaled down
    (size,) = page.state_buttons["call"].icon().availableSizes()
    assert size == DOT_ICON * page.state_buttons["call"].devicePixelRatioF()
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


def test_a_place_shows_what_it_takes_from_its_channel_or_pool(window: MainWindow):
    page = panel(window)
    window.document.set(("channel", "out", "rec"), "muted")
    window.document.set(("channel", "out", "lit_when_idle"), True)
    window.document.set(("pool", "auto", "color"), "green")
    window.document.set(("pool", "auto", "max_volume"), 110)
    window.document.set(("pool", "outs"), {"channels": ["out"]})
    window.document.set(("slots", "3"), ["outs", "devices", "-"])
    window.editor.edited()

    page.select_slot(1)
    assert page.place_title.text() == "Look in slot 1"
    assert plain(page.place_parts.text()) == "What the parts of out do is set on the channel."
    assert page.channel_button.text() == "Edit the channel"
    rows = {option_row.option.name: option_row for option_row in page.place_rows}
    assert rows["label"].line.placeholderText() == "As on the channel: Speaker"
    assert rows["color"].colors.swatches["cyan"].isChecked()
    assert rows["lit_when_idle"].switch.isChecked()
    assert rows["rec"].buttons.combos["led"].placeholderText() == "As on the channel: muted"
    assert rows["solo"].buttons.combos["led"].placeholderText() == "As on the channel: off"
    assert rows["meter"].combo.placeholderText() == "As on the channel: pre_fader"
    assert plain(rows["rec"].help.text()).startswith(
        "What the LED of Rec shows while slot 1 shows out. Unset: as on the channel."
    )
    assert plain(rows["color"].help.text()).startswith(
        "The backlight of the LCD while slot 1 shows out. Unset: as on the channel: cyan."
    )
    assert rows["color"].reset.isHidden()
    assert rows["color"].reset.toolTip() == "Unset: as on the channel"
    # set at the place, and back to the channel's
    rows["color"].colors.swatches["red"].click()
    assert window.document.get(("slots", "1", 0)) == {"show": "out", "color": "red"}
    assert rows["color"].colors.swatches["red"].isChecked()
    rows["color"].reset.click()
    assert window.document.get(("slots", "1")) == "out"
    assert rows["color"].colors.swatches["cyan"].isChecked()

    # a pool: its own options, else those of the strip type
    page.select_slot(2)
    page.lists[1].setCurrentRow(1)
    assert plain(page.place_parts.text()) == "What the parts of auto do is set in the pool."
    rows = {option_row.option.name: option_row for option_row in page.place_rows}
    assert rows["encoder"].combo.placeholderText() == "As in the pool: pick"
    assert rows["color"].colors.swatches["green"].isChecked()
    assert not rows["lit_when_idle"].switch.isChecked()
    assert rows["rec"].buttons.combos["led"].placeholderText() == "As in the pool: recording"
    assert rows["min_volume"].spin.specialValueText() == "As in the pool: 0 %"
    assert rows["max_volume"].spin.specialValueText() == "As in the pool: 110 %"
    assert plain(rows["encoder"].help.text()).startswith(
        "What the encoder does while slot 2 shows an application of auto without a channel. Unset: as in [pool.auto]."
    )
    assert rows["color"].reset.toolTip() == "Unset: as in pool auto"

    # a pool of channels: its channels bring their look, the place has none
    page.select_slot(3)
    page.lists[2].setCurrentRow(0)
    assert not page.place_header.isHidden()
    assert page.place.isHidden()
    assert page.place_rows == []
    assert plain(page.place_parts.text()).startswith("Each channel of outs brings its own look")
    assert page.channel_button.text() == "Edit the pool"
    page.channel_button.click()
    assert window.channels_page.selection == ("pool", "outs")
    window.show_page("slots")

    page.lists[2].setCurrentRow(1)
    rows = {option_row.option.name: option_row for option_row in page.place_rows}
    assert rows["select"].buttons.combos["press"].placeholderText() == "As in the pool: default"
    assert rows["encoder"].combo.placeholderText() == "As in the pool: balance"
    assert plain(rows["encoder"].help.text()).startswith(
        "What the encoder does while slot 3 shows a device of devices. Unset: as in [pool.devices]."
    )

    # nothing: no look
    page.lists[2].setCurrentRow(2)
    assert page.place_header.isHidden()


def crumb(page: SlotsPanel, text: str) -> QToolButton:
    """The crumb of the path in the inspector with `text`."""
    layout = page.crumbs
    widgets = [layout.itemAt(index).widget() for index in range(layout.count())]  # pyright: ignore[reportOptionalMemberAccess]
    return next(each for each in widgets if isinstance(each, QToolButton) and shown(each) == text)


def shown(button: QToolButton) -> str:
    """The text of a crumb as it reads, after its dot (an icon): ● what the slot shows, ○ where it has nothing."""
    mark = button.property("mark")
    return f"{mark} {button.text()}" if mark else button.text()


def test_the_rows_that_are_no_candidate_can_be_picked(qtbot: QtBot, window: MainWindow):
    page = panel(window)
    # slot 2 is dark: its pool has nothing to hand out
    live = snapshot((0, 1, None))
    views = list(live.slots.slots)  # pyright: ignore[reportOptionalMemberAccess]
    views[1] = SlotView(2, 1, None, "auto", None, ("shows nothing: auto has nothing for it",))
    live = dataclasses.replace(live, slots=dataclasses.replace(live.slots, slots=tuple(views)))  # pyright: ignore[reportArgumentType]
    page.snapshot = lambda: live
    page.show_live(live)
    stack = page.lists[1]
    end = stack.end_row()
    assert end == 2
    stack.setCurrentRow(end)
    assert (page.slot, page.candidate, page.end) == (2, None, True)
    assert plain(page.hint.text()).startswith("The strip is dark")
    assert stack.currentRow() == end
    # it stays picked while the cards are built again, and can't be moved
    page.show_live(dataclasses.replace(live))
    assert stack.currentRow() == end
    qtbot.keyClick(stack, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert texts(stack)[:2] == ["1 when call → browser", "2 when app or person without a slot → auto"]
    # the path in the inspector ends in the dark strip, picked
    dark = crumb(page, "● dark")
    assert dark.isChecked()
    # clicked again: the slot alone
    dark.click()
    assert (page.slot, page.candidate, page.end) == (2, None, False)
    assert stack.currentRow() == -1
    page.show_live(live)
    dark = crumb(page, "● dark")
    dark.click()
    assert page.end
    # a candidate after it: the end is no longer picked
    stack.setCurrentRow(0)
    assert (page.candidate, page.end) == (0, False)
    first = crumb(page, "1  browser")
    assert first.isChecked()
    first.click()
    assert (page.slot, page.candidate) == (2, None)
    # the strip of a dark slot picks the end of its rail
    window.device_view.select(1)
    assert (page.slot, page.candidate, page.end) == (2, None, True)
    # it lights up: the end stays, the last option without the dot, and the strip picks what it shows
    lit = snapshot((0, 1, None))
    page.snapshot = lambda: lit
    page.show_live(lit)
    assert texts(stack) == [
        "1 when call → browser",
        "▶ 2 when app or person without a slot → auto",
        "nothing to show: the strip goes dark",
    ]
    assert stack.end_row() == 2
    assert crumb(page, "dark").toolTip().startswith("When none of the candidates")
    assert plain(page.hint.text()).startswith("When none of the candidates has anything to show")
    window.device_view.select(1)
    assert (page.slot, page.candidate, page.end) == (2, 1, False)
    page.snapshot = lambda: live
    page.show_live(live)
    # `auto` of an empty slot picks the slot
    page.lists[2].setCurrentRow(0)
    assert (page.slot, page.candidate, page.end) == (3, None, True)
    assert plain(page.hint.text()).startswith("Slot 3 has no candidate")


def test_the_chip_of_what_a_candidate_shows_has_the_colors_of_its_lcd(window: MainWindow):
    page = panel(window)
    window.document.set(("slots", "1"), [{"show": "out", "color": "red"}])
    window.document.set(("slots", "3"), "-")
    window.editor.edited()
    row = page.lists[0].itemWidget(page.lists[0].item(0))  # pyright: ignore[reportArgumentType]
    assert row is not None
    (shows,) = row.findChildren(ShowChip)
    assert shows.text() == "out"
    assert shows.colors == ("red",)
    assert "The LCD: red (color of this candidate)" in shows.toolTip()
    # the swatches have room before the name
    assert shows.contentsMargins().left() > 0
    assert shows.grab().size() == shows.size()
    # a dark strip has no chip: a tiny dark LCD
    dark = page.lists[2].itemWidget(page.lists[2].item(0))  # pyright: ignore[reportArgumentType]
    assert dark is not None
    assert not dark.findChildren(ShowChip)
    assert [badge.name for badge in dark.findChildren(LcdBadge)] == ["off"]


def test_picking_a_slot_scrolls_the_cards_only_up_and_down(window: MainWindow):
    page = panel(window)
    bar = page.card_scroll.horizontalScrollBar()
    assert bar is not None
    bar.setRange(0, 100)
    bar.setValue(50)
    page.select_slot(4)
    assert bar.value() == 0


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


def test_the_inspector_has_the_controls_of_the_slot(window: MainWindow):
    window.document.set(("controls", "1"), {"select": "toggle:call"})
    window.editor.edited()
    panel(window).pick_slot(1)
    controls = panel(window).slot_controls
    assert controls.title.text() == "Controls of slot 1"
    assert [list(box.rows) for box in controls.boxes] == [["select", "id"]]


def test_simulate_needs_a_daemon(window: MainWindow):
    page = panel(window)
    assert not page.simulate_button.isEnabled()
    assert "no daemon runs" in page.simulate_button.toolTip()
    page.simulate(WhatIf())
    assert page.what_if is None


def situations(live_daemon: FakeLiveDaemon) -> list[StartPreview]:
    """The previews in the GUI with a situation of Simulate that the window sent."""
    return [
        request
        for request in live_daemon.requests
        if isinstance(request, StartPreview) and not request.on_device and request.situation is not None
    ]


def test_simulate_runs_on_the_virtual_twin_of_the_daemon(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    page = panel(window)
    device = window.device_view
    window.document.set(("state", "gaming"), {"mode": True, "processes": ["steam"]})
    window.document.set(("slots", "3"), ["browser if gaming", "-"])
    window.document.set(("slots", "4"), ["out if present", "apps"])
    window.editor.edited()
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    first = strip_state(("Real", "1%"), color="cyan")
    live_daemon.send(dataclasses.replace(device_snapshot(window, first), features=("on_device",)))
    qtbot.waitUntil(lambda: page.simulate_button.isEnabled())
    # the edits show in the GUI already, on the twin in the situation of now
    qtbot.waitUntil(lambda: any(isinstance(request, StartPreview) for request in live_daemon.requests))
    now = live_daemon.requests[0]
    assert isinstance(now, StartPreview)
    assert (now.situation, now.on_device) == (None, False)
    assert device.preview.simulating

    page.simulate_button.click()
    assert page.what_if is not None
    assert page.state_bar_row.isHidden()
    assert not page.what_if_row.isHidden()
    qtbot.waitUntil(lambda: bool(situations(live_daemon)))
    (start,) = situations(live_daemon)
    assert start.config is not None
    assert dataclasses.asdict(start.situation) == dataclasses.asdict(page.what_if)  # pyright: ignore[reportArgumentType]
    assert "[slots]" in start.config

    # until the twin shows something the drawing is what it was, and the real device is not drawn
    assert device.preview.strips[0].face.state.text == ("Real", "1%")
    twin_first = strip_state(("Twin", "2%"), color="green")
    slots = SlotsState(mode="default", mode_pick=None, slots=(), states=(), waiting={})
    live_daemon.send_twin(TwinView(start.config, (twin_first, *(strip_state() for _ in range(7))), slots))
    qtbot.waitUntil(lambda: device.preview.strips[0].face.state == twin_first)

    # each toggle has a dot: ● on or present, ○ off or absent; a click flips it
    toggles = {button.text(): button for button in page.what_if_row.findChildren(QPushButton) if button.isCheckable()}
    # grouped by what they are about: the mode, the states, the channels, the pools with their counts
    groups = [w.text() for w in page.what_if_row.findChildren(QLabelType) if w.property("role") == "group"]
    assert groups == ["MODE", "STATES", "CHANNELS", "POOLS"]
    assert set(toggles) == {"call", "out"}
    # a built-in pool is its number of members, with a dot: ○ while it is empty
    pool = page.what_if_row.findChild(QWidget, "apps")
    assert pool is not None
    (count,) = pool.findChildren(QSpinBox)
    assert count.value() == 0
    assert [
        dot.property("lit") for dot in pool.findChildren(QLabelType) if dot.pixmap() and not dot.pixmap().isNull()
    ] == [False]
    for name, toggle in toggles.items():
        assert toggle.property("lit") is not None, name
        assert toggle.toolTip().startswith((name, "The pool", "No application", "An application")), name
    channel = next(name for name, toggle in toggles.items() if toggle.toolTip().endswith("is present. Click: absent."))
    assert toggles[channel].property("lit") is True
    toggles[channel].click()
    # the bar is built anew: the old one goes
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    (flipped,) = (button for button in page.what_if_row.findChildren(QPushButton) if button.text() == channel)
    assert flipped.property("lit") is False
    assert flipped.isChecked()
    # the bar of what-ifs goes to the twin again
    (mode,) = page.what_if_row.findChildren(QComboBox)
    mode.setCurrentText("gaming")
    qtbot.waitUntil(lambda: len(situations(live_daemon)) == 2)
    last = situations(live_daemon)[-1]
    assert last.situation is not None
    assert last.situation.mode == "gaming"

    # Play plays on the twin
    window.device_view.play_button.setChecked(True)
    assert window.device_view.hand_pill.text() == "the twin of the preview"
    window.device_view.preview.device_hand.press(0, Button.MUTE, True)  # pyright: ignore[reportOptionalMemberAccess]
    qtbot.waitUntil(lambda: any(isinstance(request, Play) and request.preview for request in live_daemon.requests))
    window.device_view.select_button.setChecked(True)

    # Esc ends it: the edits stay in the GUI, in the situation of now
    count = len(live_daemon.requests)
    device.preview.strips[0].setFocus()
    qtbot.keyClick(device.preview.strips[0], Qt.Key.Key_Escape)
    assert page.what_if is None
    assert not page.simulate_button.isChecked()

    # the next preview it asks for (a heartbeat may come before it)
    def previews() -> list[StartPreview]:
        return [request for request in live_daemon.requests[count:] if isinstance(request, StartPreview)]

    qtbot.waitUntil(lambda: bool(previews()))
    assert (previews()[-1].situation, previews()[-1].on_device) == (None, False)
    assert device.preview.simulating
    assert device.preview.strips[0].face.state == twin_first

    # Off: the twin ends, the device is drawn as it is
    window.place_buttons[Place.OFF].click()
    qtbot.waitUntil(lambda: isinstance(live_daemon.requests[-1], EndPreview))
    assert not device.preview.simulating
    assert device.preview.strips[0].face.state.text == ("Real", "1%")
    # Simulate opened while Off shows in the GUI, and goes back to Off when it ends
    page.simulate_button.click()
    assert window.live_preview.place == Place.GUI
    page.simulate(None)
    assert window.live_preview.place == Place.OFF

    # a file with problems has nothing to simulate
    page.simulate_button.click()
    window.document.set(("slots", "3"), "nothing")
    window.editor.edited()
    assert page.what_if is None
    assert not page.simulate_button.isEnabled()


def test_the_marks_of_why_follow_the_theme(window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    page = panel(window)
    live = snapshot((0, 1, None))
    page.snapshot = lambda: live
    page.show_live(live)
    window.device_view.select(0)
    assert why(page)[1] == "→"

    def mark_color() -> str:
        item = page.why_rows.itemAtPosition(1, 0)
        assert item is not None
        widget = item.widget()
        assert widget is not None
        return widget.styleSheet()

    assert THEMES[ThemeMode.DARK].tone_good in mark_color()
    # as `set_theme` does, without restyling the whole application
    monkeypatch.setattr(style, "_current_mode", ThemeMode.LIGHT)
    page.shown_live = None
    page.show_live(live)
    assert THEMES[ThemeMode.LIGHT].tone_good in mark_color()


def test_the_what_ifs_line_up_with_the_panes_and_take_their_room_at_once(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    window.resize(1280, 900)
    window.show_page("slots")
    page = panel(window)
    window.document.set(("slots", "4"), ["out if present", "apps"])
    window.editor.edited()
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(dataclasses.replace(device_snapshot(window, strip_state(("Real", "1%"))), features=("on_device",)))
    qtbot.waitUntil(lambda: page.simulate_button.isEnabled())
    QApplication.processEvents()

    def edges(widget: QWidget) -> tuple[int, int]:
        return widget.mapTo(window, widget.rect().topLeft()).x(), widget.mapTo(window, widget.rect().topRight()).x()

    page.simulate(WhatIf())
    # laid out before anything is drawn, not once the event loop gets to it: no frame at the wrong height
    what_ifs = page.what_if_row.findChild(QFrame)
    assert what_ifs is not None
    placed = (edges(what_ifs), what_ifs.height(), page.splitter.height())
    assert what_ifs.height() > 2 * what_ifs.fontMetrics().height()
    QApplication.processEvents()
    assert (edges(what_ifs), what_ifs.height(), page.splitter.height()) == placed
    # on the left as the cards, on the right as the card of the right pane
    assert edges(what_ifs)[0] == edges(page.card_frames[0])[0]
    assert edges(what_ifs)[1] == edges(page.overview)[1]
    # and back, at once too
    page.simulate(None)
    closed = page.splitter.height()
    QApplication.processEvents()
    assert page.splitter.height() == closed


def test_a_what_if_has_the_node_of_the_candidates_and_the_mode_is_as_wide_as_its_modes(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    page = panel(window)
    window.document.set(("slots", "4"), ["out if present", "apps"])
    window.editor.edited()
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(dataclasses.replace(device_snapshot(window, strip_state(("Real", "1%"))), features=("on_device",)))
    qtbot.waitUntil(lambda: page.simulate_button.isEnabled())
    page.simulate(WhatIf())
    (toggle,) = (button for button in page.what_if_row.findChildren(QPushButton) if button.text() == "out")
    assert toggle.iconSize() == NODE_ICON
    (mode,) = page.what_if_row.findChildren(QComboBox)
    assert mode.sizeAdjustPolicy() == QComboBox.SizeAdjustPolicy.AdjustToContents
    assert mode.minimumSizeHint().width() < 200


def test_simulate_starts_from_reality_and_frames_what_differs(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    page = panel(window)
    window.document.set(("slots", "4"), ["out if present", "apps"])
    window.editor.edited()
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    # out is absent in reality, one application plays, call is on
    now = Situation("default", frozenset({"call"}), frozenset({"out"}), apps=1)
    slots = dataclasses.replace(snapshot((0,)).slots, now=now)  # pyright: ignore[reportArgumentType]
    real = dataclasses.replace(device_snapshot(window, strip_state(("Real", "1%"))), features=("on_device",))
    live_daemon.send(dataclasses.replace(real, slots=slots))
    qtbot.waitUntil(lambda: page.simulate_button.isEnabled())
    qtbot.waitUntil(lambda: page.snapshot() is not None and page.snapshot().slots is not None)  # pyright: ignore

    page.simulate_button.click()
    assert page.what_if == WhatIf("default", frozenset({"call"}), frozenset({"out"}), apps=1)
    toggles = {button.text(): button for button in page.what_if_row.findChildren(QPushButton) if button.isCheckable()}
    # as it is: out absent (a ring), call on (filled); nothing differs, so nothing has a frame
    assert toggles["out"].property("lit") is False
    assert toggles["call"].property("lit") is True
    assert not any(toggle.isChecked() for toggle in toggles.values())
    pool = page.what_if_row.findChild(QWidget, "apps")
    assert pool is not None
    (count,) = pool.findChildren(QSpinBox)
    assert count.value() == 1
    # a click makes out present: it differs from reality now
    toggles["out"].click()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    (out,) = (button for button in page.what_if_row.findChildren(QPushButton) if button.text() == "out")
    assert out.property("lit") is True
    assert out.isChecked()
    # reality changes meanwhile: where it started stays
    live_daemon.send(dataclasses.replace(real, slots=dataclasses.replace(slots, now=Situation())))
    page.simulate(page.what_if)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    (out,) = (button for button in page.what_if_row.findChildren(QPushButton) if button.text() == "out")
    assert out.isChecked()


def test_a_what_if_clicked_at_the_bottom_of_the_cards_keeps_their_scroll_and_its_focus(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    window.resize(1280, 700)
    window.show_page("slots")
    page = panel(window)
    window.document.set(("slots", "4"), ["out if present", "apps"])
    window.editor.edited()
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(dataclasses.replace(device_snapshot(window, strip_state(("Real", "1%"))), features=("on_device",)))
    qtbot.waitUntil(lambda: page.simulate_button.isEnabled())
    page.simulate(WhatIf())
    QApplication.processEvents()
    bar = page.card_scroll.verticalScrollBar()
    assert bar is not None
    bar.setValue(bar.maximum())
    bottom = bar.value()
    assert bottom > 0
    (out,) = (button for button in page.what_if_row.findChildren(QPushButton) if button.text() == "out")
    out.setFocus()
    out.click()
    QApplication.processEvents()
    # the bar was made anew without getting shorter for a moment, and the new out has the focus
    assert bar.value() == bottom
    focused = QApplication.focusWidget()
    assert isinstance(focused, QPushButton)
    assert focused.text() == "out"
    assert focused is not out
