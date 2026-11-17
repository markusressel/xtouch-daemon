"""
The service and the file: installing, starting and stopping the service, saving and applying.
"""

import dataclasses
import signal
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QSettings, Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QToolButton,
)
from pytestqt.qtbot import QtBot

from tests.support.gui import (
    MISSING,
    RUNNING,
    STOPPED,
    Dialogs,
    FakeLiveDaemon,
    MakeWindow,
    click,
    row,
    show_channel,
    snapshot,
    strip_state,
    type_into,
)
from tests.support.instance import RecordingInstance
from tests.support.packaging import install_package
from tests.support.systemd import FakeSystemctl
from xtouch_daemon.gui import qt
from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.channels import channel_options
from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.qt.fields.controls import Switch
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.fields.tables import Tables
from xtouch_daemon.gui.qt.theme.style import current_mode, load_theme_mode
from xtouch_daemon.gui.qt.theme.tokens import (
    ThemeMode,
)
from xtouch_daemon.gui.qt.window import service as service_module
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.system import systemd
from xtouch_daemon.system.systemd import UNIT_NAME, ServiceError, unit_file, unit_path


@pytest.mark.parametrize(
    ("properties", "pill", "tone", "button", "command"),
    [
        (MISSING, "not installed", "warn", "Install and start", ["systemctl", "--user", "daemon-reload"]),
        (STOPPED, "stopped", "neutral", "Start", ["systemctl", "--user", "enable", "--now", UNIT_NAME]),
        (RUNNING, "running", "good", "Restart", ["systemctl", "--user", "restart", UNIT_NAME]),
    ],
)
def test_the_service_is_shown_and_controlled(
    qtbot: QtBot,
    make_window: MakeWindow,
    systemctl: FakeSystemctl,
    monkeypatch: pytest.MonkeyPatch,
    properties: str,
    pill: str,
    tone: str,
    button: str,
    command: list[str],
    isolated: Dialogs,
):
    monkeypatch.setattr(service_module, "executable", lambda: "/opt/xtouch-daemon")
    systemctl.properties = properties
    window = make_window()
    assert (
        window.service_controls.pill.text(),
        window.service_controls.pill.property("tone"),
        window.service_controls.service_button.text(),
    ) == (pill, tone, button)
    isolated.answer = QMessageBox.StandardButton.Yes

    click(qtbot, window.service_controls.service_button)

    assert command in systemctl.commands
    assert window.status.text().endswith("the service.")
    # installing and starting ask first, a restart of the running service doesn't
    assert len(isolated.shown) == (0 if properties == RUNNING else 1)


@pytest.mark.parametrize("properties", [MISSING, STOPPED])
def test_a_service_is_installed_or_started_only_when_confirmed(
    qtbot: QtBot, make_window: MakeWindow, systemctl: FakeSystemctl, isolated: Dialogs, tmp_path: Path, properties: str
):
    systemctl.properties = properties
    window = make_window()
    shows = len(systemctl.commands)

    isolated.answer = QMessageBox.StandardButton.No
    click(qtbot, window.service_controls.service_button)

    assert systemctl.commands[shows:] == []
    assert not (tmp_path / "systemd").exists()
    assert window.status.text() == ""


@pytest.mark.parametrize(("properties", "stop"), [(RUNNING, True), (STOPPED, False), (MISSING, False)])
def test_only_a_running_service_can_be_stopped(
    make_window: MakeWindow, systemctl: FakeSystemctl, properties: str, stop: bool
):
    systemctl.properties = properties

    window = make_window()

    assert window.service_controls.stop_button.isHidden() is not stop


def test_the_service_is_stopped_and_can_be_started_again(
    qtbot: QtBot, window: MainWindow, systemctl: FakeSystemctl, isolated: Dialogs
):
    assert window.service_controls.stop_button.focusPolicy() == Qt.FocusPolicy.NoFocus

    def stop(command: list[str]) -> str:
        if command[2] == "stop":
            systemctl.properties = STOPPED
        return systemctl(command)

    window.service._run = stop
    click(qtbot, window.service_controls.stop_button)

    assert ["systemctl", "--user", "stop", UNIT_NAME] in systemctl.commands
    # stopped, not disabled: it starts again with the next session
    assert ["systemctl", "--user", "disable", UNIT_NAME] not in systemctl.commands
    assert window.status.text() == "Stopped the service."
    assert isolated.shown == []
    assert (window.service_controls.pill.text(), window.service_controls.service_button.text()) == ("stopped", "Start")
    assert window.service_controls.stop_button.isHidden()


def test_a_failing_stop_is_reported(qtbot: QtBot, window: MainWindow, isolated: Dialogs):
    def fail(command: list[str]) -> str:
        raise ServiceError("systemctl --user stop failed: nope")

    window.service._run = fail
    click(qtbot, window.service_controls.stop_button)

    assert isolated.shown == ["systemctl --user stop failed: nope"]
    assert window.status.text() == ""
    assert window.service_controls.stop_button.isHidden()


def test_a_daemon_elsewhere_can_not_be_stopped_here(make_window: MakeWindow, path: Path):
    window = make_window(find_daemon=lambda: RecordingInstance(4242, path.resolve(), systemd=False))

    assert window.service_controls.stop_button.isHidden()


CHECKOUT = "/home/me/xtouch-daemon/.venv/bin/xtouch-daemon"


def unit_properties(state: str, unit: Path, program: str) -> str:
    """`systemctl show` of a service with its unit file and the program it starts."""
    return f"{state}FragmentPath={unit}\nExecStart={{ path={program} ; argv[]={program} run ; ignore_errors=no }}\n"


def write_user_unit() -> None:
    unit_path().parent.mkdir(parents=True)
    unit_path().write_text(unit_file(CHECKOUT))


def test_the_header_shows_which_unit_runs_the_service(make_window: MakeWindow, systemctl: FakeSystemctl):
    systemctl.properties = unit_properties(
        RUNNING, Path("/home/me/.config/systemd/user/xtouch-daemon.service"), CHECKOUT
    )
    window = make_window()

    assert window.service_controls.unit_label.text() == f"from {CHECKOUT}"
    assert (
        window.service_controls.unit_label.toolTip() == "The unit /home/me/.config/systemd/user/xtouch-daemon.service"
    )
    # without a package there is nothing it overrides
    assert window.service_controls.override_button.isHidden()

    systemctl.properties = unit_properties(RUNNING, systemd.PACKAGED_UNIT, "/usr/bin/xtouch-daemon")
    window.refresh_service()
    assert window.service_controls.unit_label.text() == "packaged"

    systemctl.properties = MISSING
    window.refresh_service()
    assert window.service_controls.unit_label.isHidden()


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_the_unit_that_overrides_the_package_can_be_removed(
    qtbot: QtBot,
    make_window: MakeWindow,
    systemctl: FakeSystemctl,
    isolated: Dialogs,
    answer: QMessageBox.StandardButton,
):
    install_package()
    write_user_unit()
    systemctl.properties = unit_properties(RUNNING, unit_path(), CHECKOUT)
    window = make_window()
    assert not window.service_controls.override_button.isHidden()
    assert window.service_controls.unit_label.property("role") == "hint"
    assert window.service_controls.unit_label.toolTip().endswith(", which overrides the one of the package")
    assert window.service_controls.override_button.focusPolicy() == Qt.FocusPolicy.NoFocus
    isolated.answer = answer

    click(qtbot, window.service_controls.override_button)

    assert isolated.shown[0].startswith(f"Remove {unit_path()}?")
    if answer == QMessageBox.StandardButton.No:
        assert unit_path().exists()
        assert ["systemctl", "--user", "disable", UNIT_NAME] not in systemctl.commands
        return
    assert not unit_path().exists()
    assert ["systemctl", "--user", "restart", UNIT_NAME] in systemctl.commands
    assert window.status.text() == f"Removed {unit_path()}: the service uses the unit of the package."
    assert window.service_controls.override_button.isHidden()


def test_a_failing_removal_of_the_override_is_reported(
    qtbot: QtBot, make_window: MakeWindow, systemctl: FakeSystemctl, isolated: Dialogs
):
    install_package()
    write_user_unit()
    window = make_window()

    def fail(command: list[str]) -> str:
        if command[2] == "show":
            return RUNNING
        raise ServiceError("systemctl --user disable failed: nope")

    window.service._run = fail
    isolated.answer = QMessageBox.StandardButton.Yes
    click(qtbot, window.service_controls.override_button)

    assert isolated.shown[1:] == ["systemctl --user disable failed: nope"]
    assert window.status.text() == ""


def test_the_package_starts_its_own_unit(
    qtbot: QtBot, make_window: MakeWindow, systemctl: FakeSystemctl, isolated: Dialogs
):
    install_package()
    systemctl.properties = MISSING
    window = make_window()
    assert window.service_controls.service_button.toolTip() == "Enable the unit of the package and start it"
    isolated.answer = QMessageBox.StandardButton.Yes

    click(qtbot, window.service_controls.service_button)

    assert isolated.shown == [
        f"Enable {UNIT_NAME} of the package (it starts with the session from now on) and start it?"
    ]
    assert not unit_path().exists()
    assert ["systemctl", "--user", "enable", "--now", UNIT_NAME] in systemctl.commands
    assert window.status.text() == "Enabled the unit of the package and started the service."


def test_restart_stands_out_when_the_daemon_runs_an_older_version(
    qtbot: QtBot,
    make_window: MakeWindow,
    systemctl: FakeSystemctl,
    live_daemon: FakeLiveDaemon,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(service_module, "executable", lambda: "/usr/bin/xtouch-daemon")
    monkeypatch.setattr(service_module, "installed_version", lambda: "0.2.0")
    systemctl.properties = unit_properties(RUNNING, systemd.PACKAGED_UNIT, "/usr/bin/xtouch-daemon")
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    current = dataclasses.replace(snapshot(window, strip_state()), daemon_version="0.2.0")
    live_daemon.send(current)
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    window.refresh_service()
    assert window.service_controls.service_button.property("variant") == ""
    assert window.service_controls.service_button.toolTip() == "Restart the daemon, e.g. after changing the device name"

    # after an upgrade of the package
    live_daemon.send(dataclasses.replace(current, daemon_version="0.1.0"))
    qtbot.waitUntil(lambda: window.live.snapshot is not None and window.live.snapshot.daemon_version == "0.1.0")
    window.refresh_service()

    assert window.service_controls.service_button.text() == "Restart"
    assert window.service_controls.service_button.property("variant") == "primary"
    assert window.service_controls.service_button.toolTip() == (
        "The daemon runs version 0.1.0, 0.2.0 is installed: restart it to run 0.2.0"
    )


def test_a_new_window_starts_with_the_keys_on_the_strips(window: MainWindow):
    assert window.focusWidget() is window.device_view.preview.strips[0]


def test_keys_typed_into_a_new_window_do_not_press_the_service_button(window: MainWindow):
    assert window.service_controls.service_button.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_a_failing_systemctl_is_reported(qtbot: QtBot, make_window: MakeWindow, systemctl, isolated: Dialogs):
    window = make_window()

    def fail(command: list[str]) -> str:
        raise ServiceError("systemctl --user restart failed: nope")

    window.service._run = fail
    click(qtbot, window.service_controls.service_button)
    assert isolated.shown == ["systemctl --user restart failed: nope"]
    assert window.service_controls.pill.text() == "unavailable"
    assert window.service_controls.service_button.isHidden()


def test_a_changed_device_offers_a_restart(qtbot: QtBot, window: MainWindow, systemctl: FakeSystemctl):
    window.document.set(("device", "name"), "Other")
    window.editor.edited()

    assert window.save()
    assert not window.restart_button.isHidden()

    click(qtbot, window.restart_button)
    assert systemctl.commands[-2] == ["systemctl", "--user", "restart", UNIT_NAME]
    assert window.status.text() == "Restarted the service."


def test_a_changed_mqtt_section_offers_a_restart_instead_of_a_reload(window: MainWindow, daemon: RecordingInstance):
    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.editor.edited()

    assert window.save()

    assert daemon.reloads == []
    assert window.status.text() == "Saved. The [mqtt] section changed: restart the service to use the configuration."
    assert not window.restart_button.isHidden()


def test_a_failing_restart_or_reload_is_reported(
    qtbot: QtBot, window: MainWindow, systemctl: FakeSystemctl, isolated: Dialogs
):
    window.document.set(("device", "name"), "Other")
    window.editor.edited()
    window.save()

    def fail(command: list[str]) -> str:
        if command[2] == "show":
            return RUNNING
        raise ServiceError(f"{command[2]} failed")

    window.service._run = fail
    click(qtbot, window.restart_button)
    assert isolated.shown == ["restart failed"]

    # it ended a moment ago
    window.daemon = RecordingInstance(1234, window.document.path.resolve(), systemd=True, gone=True)
    window.document.set(("device", "name"), "Third")
    window.editor.edited()
    assert window.save()
    assert window.status.text() == "Saved, but reloading the service failed: [Errno 3] No such process"


def test_a_daemon_started_elsewhere_is_shown_and_reloaded(qtbot: QtBot, make_window: MakeWindow, path: Path):
    daemon = RecordingInstance(4242, path.resolve(), systemd=False)
    window = make_window(find_daemon=lambda: daemon)

    assert (window.service_controls.pill.text(), window.service_controls.pill.property("tone")) == (
        "running elsewhere",
        "good",
    )
    assert "process 4242" in window.service_controls.pill.toolTip()
    assert window.service_controls.service_button.isHidden()
    assert window.service_controls.unit_label.isHidden()
    assert window.service_controls.override_button.isHidden()

    window.document.set(("device", "name"), "Other")
    window.editor.edited()
    assert window.save()

    assert daemon.reloads == [4242]
    assert window.status.text().endswith("restart the daemon (process 4242) for that to take effect.")
    # the window restarts only the service
    assert window.restart_button.isHidden()


def test_without_a_daemon_saving_only_saves(make_window: MakeWindow, systemctl: FakeSystemctl):
    systemctl.properties = STOPPED
    window = make_window(find_daemon=lambda: None)
    window.document.set(("device", "name"), "Other")
    window.editor.edited()

    assert window.save()

    assert window.status.text() == "Saved. The daemon is not running: start it to use the configuration."
    assert window.restart_button.isHidden()


def test_saving_what_did_not_change_does_nothing(window: MainWindow, path: Path):
    before = path.stat().st_mtime_ns
    assert window.save()
    assert path.stat().st_mtime_ns == before


def test_a_file_that_can_not_be_written_is_reported(window: MainWindow, path: Path, isolated: Dialogs):
    window.document.set(("behavior", "max_volume"), 110)
    window.editor.edited()
    path.chmod(0o400)
    try:
        assert not window.save()
    finally:
        path.chmod(0o600)
    assert isolated.shown[0].startswith("[Errno 13] Permission denied")


def test_a_new_file_can_be_saved_right_away(make_window: MakeWindow, tmp_path: Path):
    window = make_window(file=tmp_path / "new.toml")

    assert window.path_label.text().endswith("new file")
    assert window.save_button.isEnabled()
    assert window.save()
    assert "slots" in tomllib.loads((tmp_path / "new.toml").read_text())
    assert window.status.text().startswith("Saved. The service reads")


def test_revert_drops_the_changes(qtbot: QtBot, window: MainWindow):
    window.document.unset(("channel", "browser"))
    window.editor.edited()

    click(qtbot, window.revert_button)

    assert window.document.get(("channel", "browser", "label")) == "Browser"
    assert window.status.text() == "Reverted to the file. Ctrl+Z brings the changes back."


@pytest.mark.parametrize(
    ("answer", "closed", "saved"),
    [
        (QMessageBox.StandardButton.Discard, True, False),
        (QMessageBox.StandardButton.Save, True, True),
        (QMessageBox.StandardButton.Cancel, False, False),
    ],
)
def test_closing_asks_about_unsaved_changes(
    window: MainWindow, path: Path, isolated: Dialogs, answer: QMessageBox.StandardButton, closed: bool, saved: bool
):
    window.document.set(("behavior", "max_volume"), 110)
    window.editor.edited()
    isolated.answer = answer

    assert window.close() == closed
    assert isolated.shown == ["Save the changes before closing?"]
    assert ("max_volume = 110" in path.read_text()) == saved
    isolated.answer = QMessageBox.StandardButton.Discard


def test_closing_without_changes_does_not_ask(window: MainWindow, isolated: Dialogs):
    assert window.close()
    assert isolated.shown == []


def test_the_theme_switches_and_is_remembered(qtbot: QtBot, window: MainWindow):
    # in the menu View
    assert window.theme_actions[ThemeMode.DARK].isChecked()
    window.theme_actions[ThemeMode.LIGHT].trigger()
    assert current_mode() == ThemeMode.LIGHT
    assert load_theme_mode() == ThemeMode.LIGHT
    assert not window.theme_actions[ThemeMode.DARK].isChecked()

    window.theme_actions[ThemeMode.DARK].trigger()
    assert load_theme_mode() == ThemeMode.DARK
    QSettings().setValue("theme", "purple")
    assert load_theme_mode() == ThemeMode.DARK


def test_run_gui_shows_the_window(path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication):
    shown: list[MainWindow] = []
    monkeypatch.setattr(qt, "QApplication", lambda args: qapp)
    monkeypatch.setattr(MainWindow, "show", lambda window: shown.append(window))
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    handlers: dict[int, Callable[..., object]] = {}
    monkeypatch.setattr(qt.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    closed: list[bool] = []
    monkeypatch.setattr(qapp, "closeAllWindows", lambda: closed.append(True))

    assert qt.run_gui(path) == 0
    assert shown[0].document.path == path
    assert QCoreApplication.applicationName() == "xtouch-daemon-gui"
    # the name of packaging/xtouch-daemon-gui.desktop
    assert qapp.desktopFileName() == "xtouch-daemon-gui"
    # Ctrl+C closes the window like its close button
    handlers[signal.SIGINT](signal.SIGINT, None)
    assert closed == [True]
    shown[0].deleteLater()


def test_launch_is_a_list_of_the_parts_of_the_command(window: MainWindow):
    show_channel(window, "browser")
    launch = row(window, "launch")

    assert launch.chips.input.placeholderText() == (
        "Add… (none: Select starts nothing; the program, then each argument)"
    )
    link = docs.url("configuration/applications/#launching-the-application")
    assert f'<a href="{link}">Learn more</a>' in launch.help.text()
    assert "Never through a shell." in launch.help.text()
    # a part per entry
    launch.chips.add("mumble")
    launch.chips.add("mumble://me@example.org/Gaming")
    assert window.document.get(("channel", "browser", "launch")) == ["mumble", "mumble://me@example.org/Gaming"]
    assert window.document.validate().at("channel", "browser") == []


def test_the_rail_shows_one_page_at_a_time(qtbot: QtBot, window: MainWindow):
    assert window.current_page == "slots"
    assert [button.text() for button in window.rail_buttons.values()] == ["Slots", "Channels", "States", "Settings"]
    assert [button.text() for button in window.nav_buttons.values()] == [
        "Behavior",
        "Aliases",
        "Home Assistant",
        "Modes and chord",
        "Voice chat",
        "Device",
    ]
    click(qtbot, window.rail_buttons["settings"])
    assert window.current_page == "behavior"
    click(qtbot, window.rail_buttons["states"])
    assert window.current_page == "states"

    click(qtbot, window.nav_buttons["device"])
    assert window.current_page == "device"
    # the page stays when the pages are built again
    window.editor.edited()
    assert window.current_page == "device"
    click(qtbot, window.rail_buttons["slots"])
    assert window.current_page == "slots"
    # a strip of the device picks its slot
    click(qtbot, window.device_view.preview.strips[1])
    assert window.device_view.preview.strips[1].selected


def test_faders_are_picked_with_buttons(qtbot: QtBot, window: MainWindow):
    click(qtbot, window.nav_buttons["device"])
    faders = row(window, "touchless_faders", "device").numbers
    assert list(faders.buttons) == list(range(1, 9))
    assert faders.values == []

    click(qtbot, faders.buttons[3])
    click(qtbot, faders.buttons[1])
    assert window.document.get(("device", "touchless_faders")) == [1, 3]
    click(qtbot, faders.buttons[1])
    click(qtbot, faders.buttons[3])
    # none: the option goes away
    assert window.document.get(("device", "touchless_faders")) is None

    # a value of another type shows none
    window.document.set(("device", "touchless_faders"), "1")
    window.editor.edited()
    assert row(window, "touchless_faders", "device").numbers.values == []


def test_help_shows_quotes_and_code_as_they_are_meant(window: MainWindow):
    show_channel(window, "out")
    # the help of the label has quotes but no tag, which Qt would show as plain text, entities and all
    (help_label,) = [
        widget for widget in row(window, "label").findChildren(QLabel) if "start of the device" in widget.text()
    ]
    assert help_label.textFormat() == Qt.TextFormat.RichText
    document = QTextDocument()
    document.setHtml(help_label.text())
    assert '"Output"' in document.toPlainText()
    assert "&quot;" not in document.toPlainText()


def test_a_choice_says_what_the_chosen_value_means(window: MainWindow):
    show_channel(window, "out")
    rec = row(window, "rec")
    assert not rec.meaning.isHidden()
    assert "<code>recording</code>: Lit while an application records" in rec.meaning.text()
    rec.combo.setCurrentText("muted")
    assert "Lit while the strip is muted" in rec.meaning.text()
    # each value says it in the list too
    tip = rec.combo.itemData(rec.combo.findText("recording"), Qt.ItemDataRole.ToolTipRole)
    assert "screen recorder" in tip
    # an encoder that is not set: what the default does
    encoder = row(window, "encoder")
    assert encoder.combo.currentIndex() == -1
    assert "<code>balance</code>: Turn: the balance" in encoder.meaning.text()
    # a value that is no choice means nothing
    window.document.set(("channel", "out", "rec"), "loud")
    window.editor.edited()
    assert row(window, "rec").meaning.isHidden()
    assert row(window, "color").colors.swatches["off"].toolTip() == "off: No backlight."
    assert row(window, "color").colors.swatches["red"].toolTip() == "red"


def test_help_has_the_default_and_a_link_to_the_docs(window: MainWindow):
    show_channel(window, "out")
    rec = row(window, "rec")
    assert "Default: <code>recording</code>." in rec.help.text()
    assert f'<a href="{docs.url("configuration/indicators/#indicators")}">Learn more</a>' in rec.help.text()
    assert rec.help.openExternalLinks()
    # an option without a section in the docs: its help says it all
    assert "Learn more" not in row(window, "meter").help.text()
    # the pages
    for page in ("channels", "device", "behavior", "aliases", "mqtt"):
        link = docs.page_link(page)
        assert link is not None
        assert [label for label in window.pages[page].findChildren(QLabel) if link in label.text()], page
    # nothing to say: no help at all
    bare = OptionRow(Option("bare", Kind.TEXT, "", None, False), lambda: None, lambda _: None)
    assert bare.help.isHidden()


def test_profiles_are_lines_of_label_and_profile(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    profiles = row(window, "profiles")
    tables: Tables = profiles.tables
    assert tables.values == []

    click(qtbot, tables.add_button)
    type_into(qtbot, tables.lines[0][0], "Analog")
    # the profiles of the card come from the sound server
    menu_button = next(button for button in tables.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    assert [action.text() for action in menu.actions()] == [
        "output:analog-stereo    Analog Stereo Output (active)",
        "output:iec958-stereo    Digital Output",
    ]
    menu.actions()[0].trigger()
    assert tables.lines[0][1].text() == "output:analog-stereo"

    # one profile is not enough, and a label is required
    click(qtbot, tables.add_button)
    assert profiles.error.text() == "2. label: Field required\n2. profile: Field required"
    type_into(qtbot, tables.lines[1][0], "Digital")
    completer = tables.lines[1][1].completer()
    assert completer is not None
    completer.activated.emit("output:iec958-stereo")
    assert profiles.error.text() == ""

    assert window.document.get(("channel", "out", "profiles")) == [
        {"label": "Analog", "profile": "output:analog-stereo"},
        {"label": "Digital", "profile": "output:iec958-stereo"},
    ]
    type_into(qtbot, tables.lines[1][0], "")
    assert window.document.get(("channel", "out", "profiles"))[1] == {"profile": "output:iec958-stereo"}  # type: ignore[index]

    tables.remove(1)
    assert profiles.error.text() == "at least two to switch between"
    tables.remove(0)
    assert window.document.get(("channel", "out", "profiles")) is None
    assert profiles.error.text() == ""


def test_profiles_of_the_file_are_shown_and_saved_as_tables(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    window.document.set(
        ("channel", "out", "profiles"),
        [{"label": "Analog", "profile": "output:analog-stereo"}, {"label": "Digital", "profile": "Digital Output"}],
    )
    profiles = row(window, "profiles")
    profiles.load()
    assert [[line.text() for line in lines] for lines in profiles.tables.lines] == [
        ["Analog", "output:analog-stereo", "", ""],
        ["Digital", "Digital Output", "", ""],
    ]
    assert 'label = "Digital"' in window.document.render()
    # something else than a list of tables shows none: its problem says what is wrong
    window.document.set(("channel", "out", "profiles"), "analog")
    profiles.load()
    assert profiles.tables.values == []


def test_tables_without_suggestions_have_no_menu(qtbot: QtBot):
    columns = next(option for option in channel_options("output") if option.name == "profiles").columns
    tables = Tables(columns, None)
    qtbot.addWidget(tables)
    tables.show_values([{"label": "Analog"}])
    assert [[line.text() for line in lines] for lines in tables.lines] == [["Analog", "", "", ""]]
    assert not [button for button in tables.findChildren(QToolButton) if button.menu()]


def test_an_unset_number_says_what_applies(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    window.document.set(("behavior", "max_volume"), 120)
    maximum = row(window, "max_volume")
    maximum.load()
    assert maximum.spin.value() == -1
    assert maximum.spin.text() == "default: 120 (behavior)"

    maximum.spin.setValue(180)
    assert window.document.get(("channel", "out", "max_volume")) == 180
    # back below the range: not set
    maximum.spin.setValue(-1)
    assert window.document.get(("channel", "out", "max_volume")) is None
    assert row(window, "min_volume").spin.text() == "default: 0"


def test_numbers_of_tables_are_numbers(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    tables: Tables = row(window, "profiles").tables
    click(qtbot, tables.add_button)
    type_into(qtbot, tables.lines[0][3], "200")
    assert window.document.get(("channel", "out", "profiles")) == [{"max_volume": 200}]
    # one that is none stays text: its problem says so
    type_into(qtbot, tables.lines[0][3], "lots")
    assert window.document.get(("channel", "out", "profiles")) == [{"max_volume": "lots"}]


def test_a_switch_looks_different_on_and_off(qtbot: QtBot):
    switch = Switch()
    qtbot.addWidget(switch)
    switch.resize(switch.sizeHint())
    off = switch.grab().toImage()
    switch.setChecked(True)
    assert switch.grab().toImage() != off
