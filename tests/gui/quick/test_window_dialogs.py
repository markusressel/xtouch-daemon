"""The dialogs of the window in Qt Quick (driven through their QML), the details popovers, the quit signals."""

from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QGuiApplication

from tests.gui.quick.conftest import MakeUi
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.qt.fields.popover import Entry, Group
from xtouch_daemon.gui.quick.details import Content, Details
from xtouch_daemon.gui.quick.window.dialogs import (
    CANCEL,
    DISCARD,
    OK,
    SAVE,
    SAVE_DISCARD_CANCEL,
    YES_NO,
    Dialogs,
)
from xtouch_daemon.gui.quick.window.quit import QuitWindows


def later(ui: Ui, action: Callable[[], object]) -> None:
    """Runs `action` once the dialog has shown for a frame (a popup takes clicks only then)."""

    def run() -> None:
        try:
            ui.grab()
            action()
        finally:
            # never leave the test waiting in the loop of a dialog
            QTimer.singleShot(500, ui.app.shell._dialogs.reject)  # pyright: ignore[reportPrivateUsage]

    QTimer.singleShot(200, run)


def real(make_ui: MakeUi) -> tuple[Ui, Dialogs]:
    """A window with its own dialogs, which ask for real."""
    ui = make_ui(dialogs=None)
    dialogs = ui.app.shell.dialogs
    assert isinstance(dialogs, Dialogs)
    return ui, dialogs


def test_a_question_shows_over_the_window_and_a_click_answers(make_ui: MakeUi):
    ui, dialogs = real(make_ui)
    seen: list[str] = []

    def look_and_click() -> None:
        seen.append(ui.text("dialog_title"))
        seen.append(ui.text("dialog_text"))
        ui.click("dialog_discard")

    later(ui, look_and_click)
    answer = dialogs.ask("Unsaved changes", "Save the changes?", SAVE_DISCARD_CANCEL)

    assert answer == DISCARD
    assert seen == ["Unsaved changes", "Save the changes?"]
    ui.settle()
    assert not ui.shows("dialog")
    assert not dialogs.isOpen


def test_escape_answers_with_the_button_that_rejects(make_ui: MakeUi):
    ui, dialogs = real(make_ui)

    later(ui, lambda: ui.key(Qt.Key.Key_Escape))

    assert dialogs.ask("Unsaved changes", "Save?", SAVE_DISCARD_CANCEL) == CANCEL


def test_a_note_has_one_button(make_ui: MakeUi):
    ui, dialogs = real(make_ui)
    buttons: list[list[str]] = []

    def click() -> None:
        buttons.append([str(b["id"]) for b in dialogs.buttons])  # pyright: ignore[reportGeneralTypeIssues]
        ui.click("dialog_ok")

    later(ui, click)
    dialogs.tell("Not saved", "Fix the problems first.")

    assert buttons == [[OK]]


def test_a_new_question_answers_the_one_that_waits_with_its_cancel(make_ui: MakeUi):
    _ui, dialogs = real(make_ui)
    answers: list[str] = []

    def second() -> None:
        # asked from inside the loop of the first one
        QTimer.singleShot(0, lambda: dialogs.answer(SAVE))
        answers.append(dialogs.ask("Again", "And now?", SAVE_DISCARD_CANCEL))

    QTimer.singleShot(0, second)
    first = dialogs.ask("First", "Well?", YES_NO)

    assert first == "no"
    assert answers == [SAVE]
    dialogs.answer("nothing is open")


def test_a_window_that_closes_asks_in_its_own_dialog(make_ui: MakeUi):
    ui, _dialogs = real(make_ui)
    ui.app.editor.document.set(("behavior", "max_volume"), 110)
    ui.app.editor.edited()
    ui.settle()

    later(ui, lambda: ui.click("dialog_cancel"))

    assert not ui.app.shell.closeAllowed()
    assert ui.app.editor.document.modified
    assert ui.app.dialogs_open() is False


# -- the popovers -------------------------------------------------------------------------------------------------


def test_the_rows_of_a_popover_are_built_when_it_opens_and_again_while_it_is_open():
    calls: list[str] = []
    counter = {"n": 0}

    def build() -> Content:
        counter["n"] += 1
        return Content(
            "Heading",
            [
                Group("Group", "text"),
                Entry(
                    "Row",
                    Status("ok", Tone.GOOD),
                    "Explained",
                    items=(("a", "b"),),
                    actions=(("Do", lambda: calls.append("do")),),
                    toggles=(("Toggle", False, lambda on: calls.append(f"toggle {on}")),),
                ),
            ],
            "Intro",
            (("Again", lambda: calls.append("again")),),
        )

    details = Details(build, lambda text: text.upper())
    assert details.entries == []
    details.refresh_if_open()
    assert counter["n"] == 0

    details.refresh()
    assert counter["n"] == 1
    assert details.heading == "Heading"
    assert details.intro == "INTRO"
    assert details.headerActions == ["Again"]
    group, row = details.entries
    assert group["group"]
    assert group["text"] == "TEXT"
    assert row["status"] == "ok"
    assert row["text"] == "EXPLAINED"
    assert row["items"] == [{"item": "a", "note": "b"}]
    assert row["toggles"] == [{"text": "Toggle", "on": False}]

    details.run(1, 0)
    details.header(0)
    details.toggle(1, 0, True)
    assert calls == ["do", "again", "toggle True"]


def test_the_popover_of_a_pill_follows_what_changes_while_it_is_open(ui: Ui):
    ui.click("audio_pill")
    heading = ui.app.shell.audio_details.heading  # pyright: ignore[reportAttributeAccessIssue]
    assert heading == "Sound server"

    ui.app.shell._audio_failed("Gone")  # pyright: ignore[reportPrivateUsage]
    ui.settle()

    rows = ui.app.shell.audio_details.entries  # pyright: ignore[reportAttributeAccessIssue]
    assert rows[0]["status"] == "not reachable"


# -- the signals --------------------------------------------------------------------------------------------------


def test_a_signal_closes_the_windows_unless_a_question_waits(ui: Ui):
    app = QGuiApplication.instance()
    assert app is not None
    signals = QuitWindows()
    asking = {"now": True}
    signals.watch_windows(app, lambda: asking["now"])  # pyright: ignore[reportArgumentType]
    signals.asked = True
    ui.wait_until(lambda: not signals.asked)
    assert ui.window.isVisible()

    asking["now"] = False
    signals.asked = True
    ui.wait_until(lambda: not ui.window.isVisible())


def test_children_are_found(ui: Ui):
    assert isinstance(ui.app.shell.dialogs, QObject)
