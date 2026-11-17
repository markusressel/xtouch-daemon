"""
The page States: the modes and states of the file, live values, overrides, and editing them.
"""

import dataclasses

from PyQt6.QtWidgets import QListWidgetItem
from pytestqt.qtbot import QtBot

from tests.support.gui import click, row, type_into
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, SlotsState, Snapshot, StateView


def items(window: MainWindow) -> list[QListWidgetItem]:
    states = window.states_page.list
    return [item for index in range(states.count()) if (item := states.item(index)) is not None]


def test_states_are_shown_edited_added_and_removed(qtbot: QtBot, window: MainWindow):
    window.show_page("states")
    page = window.states_page
    assert page.selection == "call"
    assert [item.text() for item in items(window)] == ["call\nstate"]
    assert (page.title.text(), page.id_edit.text()) == ("State", "call")
    assert page.used.text() == "Used by: slot 2"
    assert page.live.text() == "No daemon runs these states right now."
    assert not any(segment.isVisible() for segment in page.override_buttons.values())
    assert row(window, "voice_chat", "states").switch.isChecked()

    row(window, "delay_off", "states").spin.setValue(4)
    assert window.document.get(("state", "call", "delay_off")) == 4

    menu = page.add_button.menu()
    assert menu is not None
    menu.actions()[0].trigger()
    assert page.selection == "mode"
    assert page.title.text() == "Mode"
    # modes first
    assert [item.text().split("\n")[0] for item in items(window)] == ["mode", "call"]
    assert page.used.text() == "No slot or control asks about it yet."
    menu.actions()[1].trigger()
    assert page.selection == "state"
    assert window.document.get(("state", "state")) == {}

    # a new id: only one that can be one
    for bad in ("Gaming", "call", "default"):
        type_into(qtbot, page.id_edit, bad)
        page.id_edit.editingFinished.emit()
        assert page.id_edit.property("problem") is True
    type_into(qtbot, page.id_edit, "night")
    page.id_edit.editingFinished.emit()
    assert page.selection == "night"
    assert list(window.document.get(("state",))) == ["call", "mode", "night"]
    page.id_edit.editingFinished.emit()

    page.list.setCurrentItem(items(window)[0])
    assert page.selection == "mode"
    click(qtbot, page.remove_button)
    assert "mode" not in window.document.get(("state",))
    click(qtbot, page.remove_button)
    click(qtbot, page.remove_button)
    assert page.selection is None
    assert page.empty.isVisible()
    assert not page.form.isVisible()
    page.show_live(None)
    window.undo()
    assert page.selection == "night"


def test_a_problem_of_a_state_shows_on_its_page(window: MainWindow):
    window.document.set(("state", "call", "when"), "gaming")
    window.editor.edited()

    (action,) = window.problems_menu.actions()
    action.trigger()
    assert window.current_page == "states"
    assert window.states_page.problem.text() != ""
    assert items(window)[0].text().endswith("⚠")
    window.document.set(("state", "call", "delay_on"), "x")
    window.editor.edited()
    assert row(window, "delay_on", "states").error.text() != ""


def test_the_daemon_tells_the_values_and_takes_overrides(window: MainWindow):
    window.document.set(("state", "gaming"), {"mode": True, "processes": ["steam"]})
    window.editor.edited()
    page = window.states_page
    sent: list[Request] = []
    page.request = lambda request: sent.append(request) is None
    call = StateView("call", True, False, "2026-11-17T21:04:00", "mumble runs", "on")
    gaming = StateView("gaming", False, True, None, None, "auto")
    slots = SlotsState("default", None, (), (call, gaming), {})
    snapshot = Snapshot("x", True, sound_server=True, mqtt=None, strips=(), slots=slots)
    page.snapshot = lambda: snapshot

    page.select("call")
    page.show_live(snapshot)
    assert page.live.text() == "on since 21:04 (mumble runs), override on"
    assert page.override_buttons["on"].isChecked()
    assert [item.text() for item in items(window)] == ["gaming  ○\nmode", "call  ●\nstate"]
    page.override_buttons["auto"].click()
    assert sent == [SetOverride("call", "auto")]

    # a mode is picked, not overridden
    page.select("gaming")
    assert page.override_buttons["auto"].isChecked()
    assert page.override_buttons["on"].text() == "pick"
    assert page.override_buttons["off"].isHidden()
    page.override_buttons["on"].click()
    page.override_buttons["auto"].click()
    assert sent[1:] == [SetMode("gaming"), SetMode("auto")]
    picked = dataclasses.replace(snapshot, slots=dataclasses.replace(slots, mode_pick="gaming"))
    page.show_live(picked)
    assert page.override_buttons["on"].isChecked()
    other = dataclasses.replace(snapshot, slots=dataclasses.replace(slots, mode_pick="other"))
    page.show_live(other)
    assert not any(segment.isChecked() for segment in page.override_buttons.values())
