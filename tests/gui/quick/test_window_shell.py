"""The window in Qt Quick around the pages: panels, theme, status line, preview, problems, popovers, the trial."""

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QPointF, QProcess, QSettings
from PyQt6.QtTest import QTest

from tests.gui.quick.conftest import MakeUi
from tests.support.dialogs import FakeDialogs
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.tokens import ThemeMode
from xtouch_daemon.gui.quick import errors
from xtouch_daemon.gui.quick.details import Entry
from xtouch_daemon.gui.quick.theme import load_mode
from xtouch_daemon.gui.quick.window import messages
from xtouch_daemon.gui.quick.window.hover import first_paragraph
from xtouch_daemon.gui.quick.window.panels import Panels

MOUSE: Any = QTest


def children(ui: Ui, name: str) -> QObject:
    for item in ui.all_items():
        for child in item.children():
            if child.objectName() == name:
                return child
    raise AssertionError(f"no object named {name!r}")


def is_open(ui: Ui, name: str) -> bool:
    return children(ui, name).property("opened") is True


def edit(ui: Ui) -> None:
    ui.app.editor.document.set(("behavior", "max_volume"), 110)
    ui.app.editor.edited()
    ui.settle()


# -- the layout ---------------------------------------------------------------------------------------------------


def test_the_device_is_above_the_configuration_at_first_and_the_log_is_hidden(ui: Ui):
    panels = ui.app.shell.panels
    assert (panels.device.place, panels.device.shown) == ("top", True)  # pyright: ignore[reportAttributeAccessIssue]
    assert (panels.log.place, panels.log.shown) == ("bottom", False)  # pyright: ignore[reportAttributeAccessIssue]
    assert ui.shows("devicePanel")
    assert not ui.shows("logPanel")
    device = ui.item("devicePanel")
    page = ui.item("page_slots")
    assert device.mapToScene(QPointF(0, 0)).y() < page.mapToScene(QPointF(0, 0)).y()


def test_a_panel_goes_to_another_side_and_the_window_remembers_it(make_ui: MakeUi, ui: Ui):
    ui.app.shell.trigger("device.place.left")
    ui.app.shell.trigger("log")
    ui.app.shell.trigger("log.place.right")
    ui.grab()
    ui.grab()

    device = ui.item("devicePanel")
    page = ui.item("page_slots")
    assert device.mapToScene(QPointF(0, 0)).x() < page.mapToScene(QPointF(0, 0)).x()
    log = ui.item("logPanel")
    assert log.mapToScene(QPointF(0, 0)).x() > page.mapToScene(QPointF(0, 0)).x()
    assert QSettings().value("panels/device/place") == "left"
    assert QSettings().value("panels/log/place") == "right"

    # the next window
    after = make_ui()
    panels = after.app.shell.panels
    assert panels.device.place == "left"  # pyright: ignore[reportAttributeAccessIssue]
    assert panels.log.place == "right"  # pyright: ignore[reportAttributeAccessIssue]
    assert panels.log.shown  # pyright: ignore[reportAttributeAccessIssue]


def test_a_panel_in_a_window_of_its_own_and_back(ui: Ui):
    ui.app.shell.trigger("device.place.window")
    ui.settle()

    window = children(ui, "deviceWindow")
    assert window.property("visible") is True
    ui.app.shell.trigger("device.place.top")
    ui.settle()
    assert window.property("visible") is False
    assert ui.shows("devicePanel")


def test_the_panels_keep_their_size_and_ignore_what_is_not_a_place():
    panels = Panels()
    panels.device_panel.setSize(500)
    panels.device_panel.setSize(3)
    panels.device_panel.setPlace("nowhere")
    assert (panels.device_panel.size, panels.device_panel.place) == (40, "top")
    QSettings().setValue("panels/log/place", "sideways")
    QSettings().setValue("panels/log/size", "wide")
    assert Panels().log_panel.place == "bottom"
    assert Panels().log_panel.size == 220


# -- theme, rail, status ------------------------------------------------------------------------------------------


def test_the_theme_and_the_rail_labels_are_remembered(make_ui: MakeUi, ui: Ui):
    before = ui.app.shell.railLabels
    ui.app.shell.trigger("theme.light")
    ui.click("rail_labels")
    assert ui.app.shell.railLabels is not before

    after = make_ui()
    assert after.app.shell.railLabels is not before
    assert load_mode() == ThemeMode.LIGHT


def test_the_status_line_shows_what_was_told_and_the_tip_under_the_mouse_on_top(ui: Ui):
    ui.app.shell.tell("Copied.")
    ui.settle()
    assert ui.text("status") == "Copied."

    button = ui.item("revert_button")
    MOUSE.mouseMove(ui.window, ui.center(button))
    ui.wait_until(lambda: ui.app.shell.hoverTip != "")
    assert ui.app.shell.hoverTip == first_paragraph(ui.app.shell.hoverTip)
    MOUSE.mouseMove(ui.window, ui.center(ui.item("page_slots")))
    ui.wait_until(lambda: ui.app.shell.hoverTip == "")
    assert ui.text("status") == "Copied."


def test_an_error_nobody_caught_goes_to_the_status_line(ui: Ui):
    errors.report(ZeroDivisionError, ZeroDivisionError("division by zero"), None)

    assert ui.app.shell.statusText == messages.error_raised("ZeroDivisionError: division by zero")


# -- the preview --------------------------------------------------------------------------------------------------


def test_the_preview_control_chooses_where_the_changes_show(ui: Ui):
    shell = ui.app.shell
    places = {place["id"]: place for place in shell.bar["places"]}
    assert set(places) == {"gui", "device", "off"}
    assert places["off"]["enabled"]
    # without a daemon neither the device nor the twin can show it: the reason leads the tip
    assert not places["device"]["enabled"]
    assert "\n\n" in places["device"]["tip"]

    shell.setPlace("off")
    assert shell.place == "off"
    assert [place["checked"] for place in shell.bar["places"]] == [False, False, True]


# -- the problems -------------------------------------------------------------------------------------------------


def test_the_problems_button_lists_what_the_daemon_would_not_take(ui: Ui):
    ui.app.editor.document.set(("behavior", "max_volume"), 999)
    ui.app.editor.edited()
    ui.settle()
    shell = ui.app.shell
    assert shell.problems
    assert ui.shows("problems_button")

    shell.pickProblem(0)

    assert ui.app.page == "settings"


def test_an_unknown_option_is_removed_by_its_click(ui: Ui):
    ui.app.editor.document.set(("behavior", "nonsense"), 1)
    ui.app.editor.edited()
    ui.settle()
    texts = ui.app.shell.problems
    assert any("unknown option, click to remove it" in text for text in texts)

    ui.app.shell.pickProblem(next(i for i, text in enumerate(texts) if "unknown option" in text))

    assert ui.app.editor.document.get(("behavior", "nonsense"), None) is None


# -- the popovers -------------------------------------------------------------------------------------------------


def test_the_sound_server_popover_lists_what_was_read_and_reads_again(ui: Ui):
    ui.click("audio_pill")
    assert is_open(ui, "audio_details")
    details = ui.app.shell.audio_details
    assert details.heading == "Sound server"  # pyright: ignore[reportAttributeAccessIssue]
    assert details.headerActions == ["Read again"]  # pyright: ignore[reportAttributeAccessIssue]

    loaded: list[int] = []
    ui.app.shell.loader.load = lambda: loaded.append(1)  # type: ignore[method-assign]
    details.header(0)  # pyright: ignore[reportAttributeAccessIssue]
    assert loaded == [1]


def test_a_second_click_on_a_pill_closes_its_popover_and_a_click_elsewhere_too(ui: Ui):
    ui.click("audio_pill")
    assert is_open(ui, "audio_details")
    # the press on the pill leaves the popover to the pill: closed by the press, the click would open it again
    ui.click("audio_pill")
    ui.settle()
    assert not is_open(ui, "audio_details")

    ui.click("audio_pill")
    assert is_open(ui, "audio_details")
    ui.click("service_pill")
    ui.settle()
    assert not is_open(ui, "audio_details")


def test_a_sound_server_that_does_not_answer_says_so(ui: Ui):
    ui.app.shell._audio_failed("No connection")  # pyright: ignore[reportPrivateUsage]
    ui.settle()

    assert ui.app.shell.bar["audio"]["text"].startswith("Sound server not reachable")


def test_the_changes_pill_names_the_file(ui: Ui, path: Path):
    ui.click("changes_pill")

    assert is_open(ui, "changes_details")
    entries = ui.app.shell.changes_details._content.entries  # pyright: ignore[reportAttributeAccessIssue,reportPrivateUsage]
    rows = [entry for entry in entries if isinstance(entry, Entry)]
    assert [entry.title for entry in rows][:2] == ["Device", "File"]
    assert rows[1].path == str(path)


# -- the trial daemon ---------------------------------------------------------------------------------------------


def sleeper() -> QProcess:
    process = QProcess()
    process.start("sleep", ["30"])
    assert process.waitForStarted()
    return process


def test_a_trial_daemon_starts_restarts_and_ends_with_the_window(make_ui: MakeUi):
    started: list[QProcess] = []

    def launch(path: Path) -> QProcess:
        started.append(sleeper())
        return started[-1]

    ui = make_ui(extra={"launch_trial": launch})
    shell = ui.app.shell
    shell.try_without_device()
    assert shell.trying is started[0]
    assert shell.statusText == messages.TRIAL_STARTING
    # a second one is no use
    shell.try_without_device()
    assert len(started) == 1

    shell.restart_daemon()
    assert shell.statusText == messages.TRIAL_STOPPING
    ui.wait_until(lambda: len(started) == 2)
    assert shell.trying is started[1]
    assert shell.statusText == messages.TRIAL_AGAIN
    assert shell.restart_reason() is None

    # the window ends: so does the daemon
    assert shell.closeAllowed()
    assert shell.trying is None
    assert started[1].state() == QProcess.ProcessState.NotRunning


def test_a_trial_daemon_that_ends_by_itself_is_told(make_ui: MakeUi):
    process = QProcess()

    def launch(path: object) -> QProcess:
        # started as the shell starts it: under load, one started before the window could end before it listens
        process.start("sh", ["-c", "sleep 0.5; exit 3"])
        return process

    ui = make_ui(extra={"launch_trial": launch})
    ui.app.shell.try_without_device()

    ui.wait_until(lambda: ui.app.shell.trying is None, timeout=10000)

    assert ui.app.shell.statusText == messages.trial_ended(3)


def test_without_a_daemon_it_can_not_be_restarted(ui: Ui):
    ui.app.shell.daemon = None
    assert ui.app.shell.restart_reason() == "No daemon runs now."


# -- closing ------------------------------------------------------------------------------------------------------


def test_closing_with_changes_asks_and_cancel_keeps_the_window(ui: Ui, dialogs: FakeDialogs):
    edit(ui)
    dialogs.answer = "cancel"
    assert not ui.app.shell.closeAllowed()
    assert dialogs.shown == ["Save the changes before closing?"]

    dialogs.answer = "save"
    assert ui.app.shell.closeAllowed()
    assert not ui.app.editor.document.modified


# -- the daemon and the virtual device -----------------------------------------------------------------------------


def test_a_restart_reason_names_why_the_daemon_can_not_be_restarted(ui: Ui):
    shell = ui.app.shell
    assert shell.restart_reason() is None
    assert shell.daemon is not None
    shell.daemon = type(shell.daemon)(shell.daemon.pid, shell.daemon.config, systemd=False)
    assert shell.restart_reason() is not None
    assert "outside the service" in (shell.restart_reason() or "")


def test_the_virtual_device_is_saved_into_the_file_and_opened(ui: Ui, path: Path):
    opened: list[int] = []
    ui.app.shell.virtualDeviceOpened.connect(lambda: opened.append(1))

    ui.app.shell.use_virtual_device()

    assert "virtual = true" in path.read_text()
    assert opened == [1]
    assert ui.app.shell.hosted is not None
    ui.app.shell.close_virtual_device()
    assert ui.app.shell.hosted is None


def test_the_virtual_device_of_another_file_is_not_touched(ui: Ui, path: Path):
    ui.app.shell.daemon = None
    ui.app.shell.use_virtual_device()

    assert "virtual" not in path.read_text()
    assert ui.app.shell.statusText.startswith("The daemon reads another file")
