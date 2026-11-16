"""
Editing in the window: what it shows of the document, changing options, undo.
"""

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PyQt6 import sip
from PyQt6.QtCore import QChildEvent, QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from tests.support.gui import CONFIG, Dialogs, MakeWindow, buttons, click, row, shows, type_into
from tests.support.instance import RecordingInstance
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def test_the_window_shows_the_configuration(window: MainWindow, path: Path):
    looks = [view.look for view in window.preview.strips]
    assert [(look.kind, look.label, look.color, look.configured) for look in looks[:3]] == [
        ("output", "Speaker", "cyan", True),
        ("apps", "Browser", "white", True),
        ("auto", "auto", "white", False),
    ]
    assert window.audio_label.text() == "Sound server: 2 outputs, 1 input, 2 applications"
    assert window.path_label.text() == f"{path}  ·  saved"
    assert not window.save_button.isEnabled()
    assert not window.problems_button.isVisible()
    assert window.service_controls.pill.text() == "running"
    assert window.service_controls.service_button.text() == "Restart"
    assert row(window, "label").line.text() == "Speaker"
    # the preview paints
    assert not window.grab().isNull()


def test_a_click_on_a_strip_edits_it(qtbot: QtBot, window: MainWindow):
    click(qtbot, window.preview.strips[1])

    assert window.selected == 1
    assert window.tabs.tabText(0) == "Strip 2 · Browser"
    assert row(window, "match").chips.values == ["brave"]


def test_without_the_sound_server_names_are_typed_by_hand(make_window: MakeWindow):
    def unreachable() -> AudioState:
        raise SoundServerError("can't reach the sound server: no socket")

    window = make_window(unreachable)

    assert window.audio_label.text() == "Sound server not reachable: type names by hand"
    assert window.audio_label.toolTip() == "can't reach the sound server: no socket"


def test_an_edit_shows_in_the_preview_and_is_saved(
    qtbot: QtBot, window: MainWindow, path: Path, daemon: RecordingInstance
):
    type_into(qtbot, row(window, "label").line, "Boxes")

    assert window.preview.strips[0].look.label == "Boxes"
    assert window.path_label.text().endswith("unsaved changes")
    assert window.save_button.isEnabled()

    click(qtbot, window.save_button)

    assert 'label = "Boxes"' in path.read_text()
    assert path.read_text().startswith("# my mixer\n")
    assert daemon.reloads == [1234]
    assert window.status.text() == "Saved and reloaded: the device shows the new configuration."
    assert not window.save_button.isEnabled()


def test_problems_are_shown_inline_and_block_saving(qtbot: QtBot, window: MainWindow, isolated: Dialogs):
    window.select(1)
    label = row(window, "label")
    type_into(qtbot, label.line, "")

    assert label.error.text() == "Field required"
    assert label.line.property("problem") is True
    assert window.problems_button.text() == "1 problem"
    assert window.preview.strips[1].look.problems == 1
    assert not window.save_button.isEnabled()

    assert not window.save()
    assert isolated.shown == ["Fix the problems first: the daemon would not take the file."]


def test_a_problem_leads_to_its_place(window: MainWindow):
    window.document.unset(("strip", 1, "label"))
    window.document.set(("behavior", "reset_volume"), 140)
    window.editor.edited()

    actions = window.problems_menu.actions()
    assert [action.text() for action in actions] == [
        "behavior: reset_volume (140) is above max_volume (120)",
        "strip[2].label: Field required",
    ]
    actions[1].trigger()
    assert window.selected == 1
    # selecting rebuilds the menu
    window.problems_menu.actions()[0].trigger()
    assert window.current_page == "behavior"
    assert window.pages["behavior"].problem.text() == "reset_volume (140) is above max_volume (120)"


def test_an_unknown_option_can_be_removed(make_window: MakeWindow, path: Path):
    path.write_text(CONFIG.replace("[aliases]", "typo = 1\n\n[aliases]"))
    window = make_window()

    (action,) = window.problems_menu.actions()
    assert action.text() == "behavior.typo: unknown option, click to remove it"
    assert window.pages["behavior"].problem.text() == "behavior.typo: Extra inputs are not permitted"

    action.trigger()

    assert window.validation.problems == []


def test_a_whole_configuration_problem_leads_to_the_section(window: MainWindow):
    window.document.set_strip_type(0, "homeassistant")
    window.editor.edited()

    (action,) = window.problems_menu.actions()
    assert action.text() == "strips in Home Assistant need an [mqtt] section"
    action.trigger()
    assert window.current_page == "mqtt"

    window.go_to(window.validation.problems[0].__class__((), "something else", "value_error"))
    assert window.current_page == "mqtt"


def test_the_type_of_a_strip_changes(qtbot: QtBot, window: MainWindow):
    (apps,) = [button for button in window.strip_page.types.buttons() if button.text() == "Apps"]

    click(qtbot, apps)

    assert window.document.strips[0].values == {"type": "apps", "label": "Speaker", "color": "cyan"}
    assert window.preview.strips[0].look.kind == "apps"
    assert row(window, "match").chips.values == []


def kept_notes(window: MainWindow) -> list[str]:
    page = window.strip_page
    labels = [label for label in page.findChildren(QLabel) if shows(label, page)]
    return [note for label in labels for note in label.text().split("<br>") if "kept from" in note.lower()]


def test_a_strip_keeps_the_options_of_its_type_for_switching_back(qtbot: QtBot, window: MainWindow, path: Path):
    def type_button(title: str) -> QPushButton:
        (button,) = [button for button in window.strip_page.types.buttons() if button.text() == title]
        return button  # pyright: ignore[reportReturnType]: the types are push buttons

    assert kept_notes(window) == []
    click(qtbot, type_button("Empty"))

    assert window.document.strips[0].values == {"type": "empty"}
    assert kept_notes(window) == [
        "Kept from Output: <code>device</code>, <code>label</code>, <code>color</code>. Switching back to Output "
        "restores them."
    ]
    window.save()
    assert '# device = "speaker"' in path.read_text()

    click(qtbot, type_button("Output"))
    assert window.document.strips[0].values == {
        "type": "output",
        "device": "speaker",
        "label": "Speaker",
        "color": "cyan",
    }
    assert kept_notes(window) == []
    # back and forth again: one step each
    window.undo()
    assert window.document.strips[0].values == {"type": "empty"}
    assert kept_notes(window)
    window.redo()
    assert window.document.strips[0].values["device"] == "speaker"


def test_kept_options_that_can_not_be_read_are_left_alone(make_window: MakeWindow, path: Path):
    path.write_text('[[strip]]\ntype = "empty"\n# kept from type = "output" (the GUI restores ...):\n# device = "x\n')
    window = make_window()

    (note,) = kept_notes(window)
    assert note.startswith("The options kept from Output are no longer readable")


def test_strips_move_and_go(qtbot: QtBot, window: MainWindow):
    def header(tip: str) -> QAbstractButton:
        (button,) = buttons(window.strip_page, QAbstractButton, lambda button: button.toolTip().startswith(tip))
        return button

    assert not header("Move it to the left").isEnabled()

    click(qtbot, header("Move it to the right"))
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    assert window.selected == 1

    click(qtbot, header("Move it to the left"))
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    assert window.selected == 0

    # its place stays: an auto strip
    click(qtbot, header("Remove the strip"))
    assert [strip.type for strip in window.document.strips] == ["auto", "apps"]


def test_a_strip_that_is_not_configured_can_be_configured(qtbot: QtBot, window: MainWindow):
    window.select(4)
    (configure,) = [
        button for button in window.strip_page.findChildren(QPushButton) if button.text() == "Configure strip 5"
    ]

    click(qtbot, configure)

    assert [strip.type for strip in window.document.strips] == ["output", "apps", "auto", "auto", "auto"]
    assert window.preview.strips[4].look.configured
    # as the device has the parts of a strip, from the top down
    assert [row.option.name for row in window.strip_page.rows] == [
        "collapse",
        "encoder",
        "color",
        "lit_when_idle",
        "meter",
        "meter_point",
        "rec",
        "solo",
        "launch",
        "launch_when_running",
        "fader",
        "min_volume",
        "max_volume",
        "id",
    ]


def test_an_empty_strip_has_no_options(window: MainWindow):
    window.editor.set_strip_type(0, "empty")

    assert window.strip_page.rows == []


def test_a_strip_without_a_valid_type_shows_why(make_window: MakeWindow, path: Path):
    path.write_text('[[strip]]\ntype = "fader"\n')
    window = make_window()

    assert window.strip_page.rows == []
    form = window.strip_page.form
    assert form is not None
    assert form.problem.text().startswith("Input tag 'fader' found using 'type'")


class LayoutPasses(QObject):
    """Counts what the window does after a change: how often its widgets were laid out anew, and resized."""

    def __init__(self, window: MainWindow):
        super().__init__()
        self.window = window
        self.resizes = 0
        self.created = 0
        app = QApplication.instance()
        assert app is not None
        app.installEventFilter(self)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        if watched is self.window and event.type() == QEvent.Type.Resize:
            self.resizes += 1
        elif event.type() == QEvent.Type.ChildAdded and isinstance(event, QChildEvent):
            child = event.child()
            # widgets, not e.g. the text documents of labels
            if child is not None and child.isWidgetType():
                self.created += 1
        return False

    def geometry(self) -> dict[int, tuple[int, int, int, int]]:
        """Where every widget that shows is."""
        widgets = self.window.findChildren(QWidget)
        # by the address of the Qt widget: a Python wrapper may be another one each time
        return {
            cast(int, sip.unwrapinstance(widget)): widget.geometry().getRect()
            for widget in widgets
            if widget.isVisible()
        }

    def passes(self, change: Callable[[], None]) -> int:
        """How many times what shows changed after `change`, until it stays (one: it changed once, and then stayed)."""
        self.resizes = self.created = 0
        states = [self.geometry()]
        change()
        for _ in range(20):
            QApplication.processEvents()
            state = self.geometry()
            if state != states[-1]:
                states.append(state)
        return len(states) - 1

    def end(self) -> None:
        app = QApplication.instance()
        assert app is not None
        app.removeEventFilter(self)


def test_selecting_a_strip_changes_the_window_once_in_place(qtbot: QtBot, window: MainWindow):
    passes = LayoutPasses(window)
    size = window.size()
    # every strip once: the forms of their types are built the first time
    for index in (1, 2, 0):
        window.select(index)

    for index in (1, 2, 0, 1):
        # at most one layout of the window, and nothing built, the window keeps its size
        assert passes.passes(lambda index=index: window.select(index)) <= 1
        assert (passes.created, passes.resizes) == (0, 0)
        assert window.size() == size
    # the same strip again changes nothing
    assert passes.passes(lambda: window.select(1)) == 0
    passes.end()


def test_the_live_view_lays_out_nothing_that_stays_the_same(qtbot: QtBot, window: MainWindow):
    passes = LayoutPasses(window)
    window.refresh_preview()
    assert passes.passes(window.refresh_preview) == 0
    assert passes.created == 0
    passes.end()


def test_editing_the_layout_being_edited_changes_nothing(qtbot: QtBot, window: MainWindow):
    with qtbot.assertNotEmitted(window.editor.changed):
        window.editor.edit_layout(window.document.layout)


def test_a_strip_of_another_type_shows_the_form_of_its_type(qtbot: QtBot, window: MainWindow):
    page = window.strip_page
    output = page.form
    window.select(1)
    apps = page.form
    window.select(0)

    # the forms stay, the strips of a type share theirs
    assert page.form is output
    assert output is not apps
    assert window.document.strips[0].type == "output"
    window.editor.set_strip_type(0, "apps")
    assert page.form is apps
    assert row(window, "match").load() is None
    assert row(window, "match").chips.values == []


def test_a_short_form_takes_its_own_height(qtbot: QtBot, window: MainWindow):
    window.show()
    page = window.strip_page
    # the form of an apps strip is the tallest (with launch), the one of an output strip shorter
    window.select(0)
    qtbot.wait(10)
    output = page.form
    assert output is not None
    window.select(1)
    qtbot.wait(10)
    apps = page.form
    assert apps is not None
    assert apps.height() > output.height()

    window.select(0)
    qtbot.wait(10)

    # no gap under it, and its fields are not stretched to fill one
    assert page.parts.height() == output.heightForWidth(page.parts.width())
    device = row(window, "device")
    assert device.height() == device.heightForWidth(device.width())


def test_edits_are_undone_and_redone(qtbot: QtBot, window: MainWindow):
    assert not window.undo_button.isEnabled()
    type_into(qtbot, row(window, "label").line, "Boxes")
    window.remove_strip(1)
    assert window.undo_button.isEnabled()

    click(qtbot, window.undo_button)
    assert len(window.document.strips) == 2
    assert window.status.text() == "Undone."
    # typing into one option is one step
    window.select(0)
    window.undo()
    assert window.document.get(("strip", 0, "label")) == "Speaker"
    assert row(window, "label").line.text() == "Speaker"
    assert not window.undo_button.isEnabled()
    window.undo()

    click(qtbot, window.redo_button)
    assert window.document.get(("strip", 0, "label")) == "Boxes"
    assert window.status.text() == "Redone."
    window.redo()
    assert len(window.document.strips) == 1
    assert not window.redo_button.isEnabled()
    window.redo()


def test_undo_works_in_a_text_field_too(qtbot: QtBot, window: MainWindow):
    line = row(window, "label").line
    type_into(qtbot, line, "Boxes")
    line.setFocus()

    qtbot.keyClick(line, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert window.document.get(("strip", 0, "label")) == "Speaker"
    # other keys reach the field
    line = row(window, "label").line
    qtbot.waitUntil(line.isVisible)
    line.end(False)
    qtbot.keyClick(line, Qt.Key.Key_Backspace)
    assert window.document.get(("strip", 0, "label")) == "Speake"


def test_a_revert_can_be_undone(qtbot: QtBot, window: MainWindow):
    window.document.remove_strip(0)
    window.editor.edited()
    click(qtbot, window.revert_button)
    assert len(window.document.strips) == 2

    window.undo()
    assert [strip.type for strip in window.document.strips] == ["auto", "apps"]
    assert window.document.modified
