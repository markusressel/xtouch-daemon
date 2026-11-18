"""
Editing in the window: what it shows of the document, the page Channels, problems, undo.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem
from pytestqt.qtbot import QtBot

from tests.support.gui import CONFIG, Dialogs, MakeWindow, click, pill, row, show_channel, type_into
from tests.support.instance import RecordingInstance
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.qt.pages.channels import APPS, AUTO, PEOPLE
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def items(window: MainWindow) -> list[QListWidgetItem]:
    channels = window.channels_page.list
    return [item for index in range(channels.count()) if (item := channels.item(index)) is not None]


def test_the_window_shows_the_configuration(window: MainWindow, path: Path):
    assert pill(window.audio_label) == "Sound server: 2 outputs, 1 input, 2 applications"
    assert window.windowTitle() == path.name
    assert not window.save_button.isEnabled()
    assert not window.problems_button.isVisible()
    assert window.service_controls.pill.text() == "running  ▾"
    assert window.current_page == "slots"
    # the channels, then the built-in pools
    assert [item.text().split("\n")[0] for item in items(window)] == [
        "Speaker  ·  out",
        "Browser  ·  browser",
        "Applications",
        "People",
        "Devices",
        "Auto",
    ]
    assert [item.text().split("\n")[1] for item in items(window)[:2]] == ["slot 1", "slot 2"]
    assert not window.grab().isNull()


def test_without_the_sound_server_names_are_typed_by_hand(make_window: MakeWindow):
    def unreachable() -> AudioState:
        raise SoundServerError("can't reach the sound server: no socket")

    window = make_window(unreachable)

    assert pill(window.audio_label) == "Sound server not reachable: type names by hand"
    assert window.audio_label.toolTip().startswith("can't reach the sound server: no socket")


def test_a_channel_is_picked_edited_and_saved(qtbot: QtBot, window: MainWindow, path: Path, daemon: RecordingInstance):
    window.show_page("channels")
    page = window.channels_page
    # the first built-in pool, until a channel is picked
    assert page.title.text() == "Applications: [pool.apps]"
    assert page.used.text() == "Used by: slot 2"
    page.list.setCurrentItem(items(window)[1])
    assert page.selection == ("channel", "browser")
    assert (page.title.text(), page.id_edit.text()) == ("Applications", "browser")
    assert page.used.text() == "Used by: slot 2"

    type_into(qtbot, row(window, "label").line, "Web")
    assert window.windowTitle() == f"• {path.name}"
    assert items(window)[1].text().startswith("Web  ·  browser")
    click(qtbot, window.save_button)

    assert 'label = "Web"' in path.read_text()
    assert path.read_text().startswith("# my mixer\n")
    assert daemon.reloads == [1234]
    assert window.windowTitle() == path.name
    # the people: no id, no use
    page.list.setCurrentItem(items(window)[3])
    assert page.selection == PEOPLE
    assert page.id_edit.isHidden()
    # the people sit on the slots of auto
    assert page.used.text() == "Used by: slot 2"
    assert not page.remove_button.isEnabled()


def test_channels_are_added_duplicated_renamed_and_removed(qtbot: QtBot, window: MainWindow):
    page = window.channels_page
    show_channel(window, "out")
    menu = page.add_button.menu()
    assert menu is not None
    assert [action.text() for action in menu.actions()] == [
        "Output",
        "Input",
        "Applications",
        "Person",
        "Home Assistant",
    ]
    menu.actions()[1].trigger()
    assert page.selection == ("channel", "input")
    assert window.document.get(("channel", "input")) == {"type": "input"}
    assert page.used.text() == "Not used by a slot, pool or state yet."
    menu.actions()[1].trigger()
    assert page.selection == ("channel", "input_2")

    click(qtbot, page.duplicate_button)
    assert page.selection == ("channel", "input_2_2")

    # a new id: only one that can be one
    for bad in ("Mic", "out", "auto"):
        type_into(qtbot, page.id_edit, bad)
        page.id_edit.editingFinished.emit()
        assert page.id_edit.property("problem") is True
        assert page.selection == ("channel", "input_2_2")
    type_into(qtbot, page.id_edit, "mic")
    page.id_edit.editingFinished.emit()
    assert page.selection == ("channel", "mic")
    assert list(window.document.get(("channel",))) == ["out", "browser", "input", "input_2", "mic"]
    assert '[channel.mic]\ntype = "input"' in window.document.render()
    # the same id again changes nothing
    page.id_edit.editingFinished.emit()

    click(qtbot, page.remove_button)
    assert "mic" not in window.document.get(("channel",))
    assert page.selection == APPS
    window.undo()
    assert "mic" in window.document.get(("channel",))


def test_problems_are_shown_inline_and_block_saving(qtbot: QtBot, window: MainWindow, isolated: Dialogs):
    show_channel(window, "browser")
    match = row(window, "match")
    match.chips.remove(0)

    assert window.channels_page.problem.text() == "an apps channel needs match"
    assert window.problems_button.text() == "1 problem"
    assert items(window)[1].text().endswith("⚠")
    assert not window.save_button.isEnabled()

    assert not window.save()
    assert isolated.shown == ["Fix the problems first: the daemon would not take the file."]


def test_a_problem_leads_to_its_place(window: MainWindow):
    window.document.set(("channel", "browser", "color"), "pink")
    window.editor.edited()

    (action,) = window.problems_menu.actions()
    assert action.text().startswith("channel.browser.color: Input should be 'off', 'red'")
    action.trigger()
    assert window.current_page == "channels"
    assert window.channels_page.selection == ("channel", "browser")
    assert row(window, "color").error.text().startswith("Input should be")

    # a problem of a section: the others are checked once it is fixed
    window.document.set(("behavior", "reset_volume"), 140)
    window.editor.edited()
    (action,) = window.problems_menu.actions()
    assert action.text() == "behavior: reset_volume (140) is above max_volume (120)"
    action.trigger()
    assert window.current_page == "behavior"
    assert window.pages["behavior"].problem.text() == "reset_volume (140) is above max_volume (120)"


def test_problems_of_other_parts_lead_to_their_pages(window: MainWindow):
    for path, page in (
        (("pool", "apps", "hold"), "channels"),
        (("pool", "people", "order"), "channels"),
        (("state", "call", "delay_on"), "states"),
        (("slots", "1", 0), "slots"),
        (("aliases", "x"), "aliases"),
    ):
        window.go_to(Problem(path, "wrong", "invalid"))
        assert window.current_page == page, path
    window.go_to(Problem(("pool", "auto"), "wrong", "invalid"))
    assert window.channels_page.selection == AUTO
    window.go_to(Problem(("pool", "people"), "wrong", "invalid"))
    assert window.channels_page.selection == PEOPLE
    # a problem of the whole file: the section it names
    window.go_to(Problem((), "channels of Home Assistant need an [mqtt] section", "invalid"))
    assert window.current_page == "mqtt"
    window.show_page("slots")
    window.go_to(Problem((), "something else", "invalid"))
    assert window.current_page == "slots"


def test_an_unknown_option_can_be_removed(make_window: MakeWindow, path: Path):
    path.write_text(CONFIG.replace("[aliases]", "typo = 1\n\n[aliases]"))
    window = make_window()

    (action,) = window.problems_menu.actions()
    assert action.text() == "behavior.typo: unknown option, click to remove it"
    assert window.pages["behavior"].problem.text() == "behavior.typo: Extra inputs are not permitted"

    action.trigger()

    assert window.validation.problems == []


def test_edits_are_undone_and_redone(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    label = row(window, "label")
    type_into(qtbot, label.line, "Boxes")
    assert window.undo_button.isEnabled()

    click(qtbot, window.undo_button)
    assert window.document.get(("channel", "out", "label")) == "Speaker"
    assert label.line.text() == "Speaker"
    assert window.status.text() == "Undone."
    assert not window.undo_button.isEnabled()

    click(qtbot, window.redo_button)
    assert window.document.get(("channel", "out", "label")) == "Boxes"
    assert window.status.text() == "Redone."
    # nothing more to redo or undo
    window.redo()
    window.editor.undo()
    window.undo()
    assert window.status.text() == ""


def test_undo_works_in_a_text_field_too(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    line = row(window, "label").line
    type_into(qtbot, line, "Boxes")
    line.setFocus()

    qtbot.keyClick(line, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert window.document.get(("channel", "out", "label")) == "Speaker"
    # other keys reach the field
    line.end(False)
    qtbot.keyClick(line, Qt.Key.Key_Backspace)
    assert window.document.get(("channel", "out", "label")) == "Speake"


def test_a_revert_can_be_undone(qtbot: QtBot, window: MainWindow):
    window.document.unset(("channel", "browser"))
    window.editor.edited()
    click(qtbot, window.revert_button)
    assert "browser" in window.document.get(("channel",))

    window.undo()
    assert "browser" not in window.document.get(("channel",))
    assert window.document.modified
