"""
The widgets of the GUI, offscreen (see conftest.py), with a fake systemctl, a fake sound server, a configuration in a
temporary directory, and the dialogs answered by the tests.
"""

import signal
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from PyQt6.QtCore import QByteArray, QCoreApplication, QEvent, QMimeData, QPoint, QPointF, QSettings, Qt
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QTextDocument
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.conftest import output, source, stream
from tests.test_instance import RecordingInstance
from tests.test_systemd import FakeSystemctl
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.gui import qt
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt import window as window_module
from xtouch_daemon.gui.qt.fields import Chips, OptionRow
from xtouch_daemon.gui.qt.pages import AliasesPage, SectionPage
from xtouch_daemon.gui.qt.preview import MIME_TYPE
from xtouch_daemon.gui.qt.window import MainWindow
from xtouch_daemon.instance import Instance
from xtouch_daemon.systemd import UNIT_NAME, Service, ServiceError

CONFIG = """\
# my mixer
[behavior]
max_volume = 120

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
device = "speaker"
label = "Speaker"
color = "cyan"

[[strip]]
type = "apps"
match = ["brave"]
label = "Browser"
"""

STATE = AudioState(
    outputs=(output("speaker"), output("buds")),
    inputs=(source("mic"),),
    streams=(stream(1, "Brave", "brave"), stream(2, "WEBRTC VoiceEngine", "Discord")),
    default_output="speaker",
)

RUNNING = "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
STOPPED = "LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\n"
MISSING = "LoadState=not-found\nActiveState=inactive\nUnitFileState=\n"


class Dialogs:
    """Answers the message boxes, and records them."""

    def __init__(self) -> None:
        self.answer = QMessageBox.StandardButton.Discard
        self.shown: list[str] = []

    def question(self, parent: object, title: str, text: str, *args: object) -> QMessageBox.StandardButton:
        self.shown.append(text)
        return self.answer

    def message(self, parent: object, title: str, text: str) -> QMessageBox.StandardButton:
        self.shown.append(text)
        return QMessageBox.StandardButton.Ok


@pytest.fixture(autouse=True)
def isolated(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dialogs:
    """QSettings, the configuration and the unit in the temporary directory, and no dialog that waits for a user."""
    QCoreApplication.setOrganizationName("xtouch-daemon-test")
    QCoreApplication.setApplicationName("xtouch-daemon-test")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    dialogs = Dialogs()
    monkeypatch.setattr(QMessageBox, "question", dialogs.question)
    monkeypatch.setattr(QMessageBox, "warning", dialogs.message)
    monkeypatch.setattr(QMessageBox, "critical", dialogs.message)
    theme.apply_theme(theme.ThemeMode.DARK)
    return dialogs


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """The configuration file the service reads."""
    result = tmp_path / "xtouch-daemon" / "config.toml"
    result.parent.mkdir()
    result.write_text(CONFIG)
    return result


@pytest.fixture
def systemctl() -> FakeSystemctl:
    return FakeSystemctl(RUNNING)


@pytest.fixture
def daemon(path: Path) -> RecordingInstance:
    """The service, which reads the file."""
    return RecordingInstance(1234, path.resolve(), systemd=True)


type MakeWindow = Callable[..., MainWindow]


@pytest.fixture
def make_window(qtbot: QtBot, path: Path, systemctl: FakeSystemctl, daemon: RecordingInstance) -> MakeWindow:
    def make(
        read_audio: Callable[[], AudioState] = lambda: STATE,
        file: Path = path,
        find_daemon: Callable[[], Instance | None] = lambda: daemon,
    ) -> MainWindow:
        window = MainWindow(ConfigDocument.open(file), Service(systemctl), read_audio, find_daemon)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitUntil(lambda: window.audio_label.text() != "Reading the sound server…")
        return window

    return make


@pytest.fixture
def window(make_window: MakeWindow) -> MainWindow:
    return make_window()


def row(window: MainWindow, name: str, page: str = "strip") -> OptionRow:
    return next(option_row for option_row in window.pages[page].rows if option_row.option.name == name)


def buttons[T: QAbstractButton](parent: QWidget, kind: type[T], match: Callable[[T], bool]) -> list[T]:
    """The buttons on `parent` that `match`, without the ones of replaced pages that wait for their deletion."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return [button for button in parent.findChildren(kind) if match(button)]


def type_into(qtbot: QtBot, edit: QLineEdit, text: str) -> None:
    edit.selectAll()
    qtbot.keyClick(edit, Qt.Key.Key_Backspace)
    qtbot.keyClicks(edit, text)


def click(qtbot: QtBot, button: object) -> None:
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # pyright: ignore[reportArgumentType]


# -- showing ------------------------------------------------------------------------------------------------------


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
    assert window.pill.text() == "running"
    assert window.service_button.text() == "Restart"
    assert row(window, "label").line.text() == "Speaker"
    # the preview paints
    assert not window.grab().isNull()


def test_a_click_on_a_strip_edits_it(qtbot: QtBot, window: MainWindow):
    click(qtbot, window.preview.strips[1])

    assert window.selected == 1
    assert window.nav_buttons["strip"].text() == "Strip 2"
    assert row(window, "match").chips.values == ["brave"]


def test_without_the_sound_server_names_are_typed_by_hand(make_window: MakeWindow):
    def unreachable() -> AudioState:
        raise SoundServerError("can't reach the sound server: no socket")

    window = make_window(unreachable)

    assert window.audio_label.text() == "Sound server not reachable: type names by hand"
    assert window.audio_label.toolTip() == "can't reach the sound server: no socket"


# -- editing ------------------------------------------------------------------------------------------------------


def test_an_edit_shows_in_the_preview_and_is_saved(
    qtbot: QtBot, window: MainWindow, path: Path, daemon: RecordingInstance
):
    type_into(qtbot, row(window, "label").line, "Boxes")

    assert window.preview.strips[0].look.label == "Boxes"
    assert window.path_label.text().endswith("changed")
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
    window.refresh()

    actions = window.problems_menu.actions()
    assert [action.text() for action in actions] == [
        "behavior: reset_volume (140) is above max_volume (120)",
        "strip[2].label: Field required",
    ]
    actions[1].trigger()
    assert window.selected == 1
    # selecting rebuilds the menu
    window.problems_menu.actions()[0].trigger()
    assert window.stack.currentIndex() == list(window.pages).index("behavior")
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
    window.refresh()

    (action,) = window.problems_menu.actions()
    assert action.text() == "homeassistant strips need an [mqtt] section"
    action.trigger()
    assert window.stack.currentIndex() == list(window.pages).index("mqtt")

    window.go_to(window.validation.problems[0].__class__((), "something else", "value_error"))
    assert window.stack.currentIndex() == list(window.pages).index("mqtt")


def test_the_type_of_a_strip_changes(qtbot: QtBot, window: MainWindow):
    (apps,) = [button for button in window.strip_page.types.buttons() if button.text() == "Apps"]

    click(qtbot, apps)

    assert window.document.strips[0].values == {"type": "apps", "label": "Speaker", "color": "cyan"}
    assert window.preview.strips[0].look.kind == "apps"
    assert row(window, "match").chips.values == []


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

    click(qtbot, header("Remove the strip"))
    assert [strip.type for strip in window.document.strips] == ["apps"]


def test_a_strip_that_is_not_configured_can_be_configured(qtbot: QtBot, window: MainWindow):
    window.select(4)
    (configure,) = [
        button for button in window.strip_page.findChildren(QPushButton) if button.text() == "Configure strip 5"
    ]

    click(qtbot, configure)

    assert [strip.type for strip in window.document.strips] == ["output", "apps", "auto", "auto", "auto"]
    assert window.preview.strips[4].look.configured
    assert [row.option.name for row in window.strip_page.rows] == ["color", "meter", "rec", "solo"]


def test_an_empty_strip_has_no_options(window: MainWindow):
    window.document.set_strip_type(0, "empty")
    window.select(0)

    assert window.strip_page.rows == []


def test_a_strip_without_a_valid_type_shows_why(make_window: MakeWindow, path: Path):
    path.write_text('[[strip]]\ntype = "fader"\n')
    window = make_window()

    assert window.strip_page.rows == []
    assert window.strip_page.problem.text().startswith("Input tag 'fader' found using 'type'")


# -- the preview: drag and drop -----------------------------------------------------------------------------------


def mime(index: int) -> QMimeData:
    data = QMimeData()
    data.setData(MIME_TYPE, QByteArray(str(index).encode()))
    return data


def test_a_strip_dropped_onto_another_moves_there(window: MainWindow):
    target = window.preview.strips[1]
    buttons, modifiers = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    move = Qt.DropAction.MoveAction
    data = mime(0)

    target.dragEnterEvent(QDragEnterEvent(QPoint(5, 5), move, data, buttons, modifiers))
    assert target.drop_target
    target.dragLeaveEvent(QDragLeaveEvent())
    assert not target.drop_target
    target.dropEvent(QDropEvent(QPointF(5, 5), move, data, buttons, modifiers))

    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    assert window.selected == 1


def test_only_configured_strips_take_a_drop(window: MainWindow):
    assert window.preview.strips[5].source_of(mime(0)) is None
    assert window.preview.strips[0].source_of(mime(0)) is None
    assert window.preview.strips[0].source_of(QMimeData()) is None
    assert window.preview.strips[0].source_of(None) is None
    buttons, modifiers = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    # the events don't own the data: it has to outlive them
    data = mime(0)
    window.preview.strips[5].dragEnterEvent(
        QDragEnterEvent(QPoint(), Qt.DropAction.MoveAction, data, buttons, modifiers)
    )
    window.preview.strips[5].dropEvent(QDropEvent(QPointF(), Qt.DropAction.MoveAction, data, buttons, modifiers))
    assert not window.preview.strips[5].drop_target
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]


def test_dragging_a_strip_starts_a_drag(qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    drags: list[bytes] = []
    monkeypatch.setattr(
        QDrag,
        "exec",
        lambda drag, *args: drags.append(bytes(drag.mimeData().data(MIME_TYPE).data())) or Qt.DropAction.MoveAction,
    )
    view = window.preview.strips[1]

    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.mouseMove(view, QPoint(12, 11))
    assert drags == []
    qtbot.mouseMove(view, QPoint(60, 60))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
    assert drags == [b"1"]

    # strips that are not configured stay where they are
    qtbot.mousePress(window.preview.strips[6], Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.mouseMove(window.preview.strips[6], QPoint(60, 60))
    qtbot.mouseRelease(window.preview.strips[6], Qt.MouseButton.LeftButton)
    assert drags == [b"1"]


# -- the fields ---------------------------------------------------------------------------------------------------


def test_numbers_switches_and_choices(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    spin = row(window, "encoder_step", "behavior").spin
    spin.setValue(3)
    assert window.document.get(("behavior", "encoder_step")) == 3

    hold = row(window, "auto_hold", "behavior").spin
    assert isinstance(hold, QDoubleSpinBox)
    hold.setValue(2.5)
    assert window.document.get(("behavior", "auto_hold")) == 2.5

    meters = row(window, "meters", "behavior")
    click(qtbot, meters.switch)
    assert window.document.get(("behavior", "meters")) is False
    assert not meters.reset.isHidden()

    click(qtbot, meters.reset)
    assert window.document.get(("behavior", "meters")) is None
    assert meters.switch.isChecked()

    rec = row(window, "rec")
    rec.combo.setCurrentText("muted")
    assert window.document.get(("strip", 0, "rec")) == "muted"


def test_colors_are_swatches(qtbot: QtBot, window: MainWindow):
    color = row(window, "color")
    assert color.colors.swatches["cyan"].isChecked()

    click(qtbot, color.colors.swatches["off"])

    assert window.document.get(("strip", 0, "color")) == "off"
    assert window.preview.strips[0].look.color == "off"
    # a value that is no color checks none
    color.colors.show_value("pink")
    assert not any(swatch.isChecked() for swatch in color.colors.swatches.values())
    assert not color.colors.grab().isNull()


def test_a_list_is_chips(qtbot: QtBot, window: MainWindow):
    window.select(1)
    chips: Chips = row(window, "match").chips

    type_into(qtbot, chips.input, "firefox")
    qtbot.keyClick(chips.input, Qt.Key.Key_Return)
    chips.add("firefox")
    chips.add("")
    assert window.document.get(("strip", 1, "match")) == ["brave", "firefox"]

    chips.remove(0)
    assert window.document.get(("strip", 1, "match")) == ["firefox"]
    assert chips.values == ["firefox"]
    # a chip, the input and the suggestions flow in the layout
    assert chips.flow.count() == 3


def test_suggestions_come_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    device = row(window, "device")
    menu_button = next(button for button in device.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    texts = [action.text() for action in menu.actions()]
    assert texts == ["speaker    speaker description (the default)", "buds    buds description"]
    menu.actions()[1].trigger()

    assert window.document.get(("strip", 0, "device")) == "buds"
    assert device.line.text() == "buds"


def test_an_empty_suggestion_list_says_so(make_window: MakeWindow):
    window = make_window(lambda: AudioState())
    window.select(1)
    menu_button = next(button for button in row(window, "match").findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    (action,) = menu.actions()
    assert action.text() == "No application plays right now"
    assert not action.isEnabled()


def test_typing_completes_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    device = row(window, "device")
    type_into(qtbot, device.line, "bu")
    completer = device.line.completer()
    assert completer is not None
    assert completer.model().stringList() == ["speaker", "buds"]  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]

    completer.activated.emit("buds")
    assert window.document.get(("strip", 0, "device")) == "buds"


def test_an_unset_label_shows_the_default(qtbot: QtBot, window: MainWindow):
    label = row(window, "label")
    click(qtbot, label.reset)

    assert window.document.get(("strip", 0, "label")) is None
    assert label.line.placeholderText() == "speaker"
    # the device decides the default label, like on the device: the start of its description, or the type
    type_into(qtbot, row(window, "device").line, "buds")
    assert label.line.placeholderText() == "buds de"
    type_into(qtbot, row(window, "device").line, "")
    assert label.line.placeholderText() == "Output"


# -- sections -----------------------------------------------------------------------------------------------------


def test_an_optional_section_is_added_and_removed(qtbot: QtBot, window: MainWindow):
    page = window.pages["mqtt"]
    assert isinstance(page, SectionPage)
    (add,) = [button for button in page.findChildren(QPushButton) if button.text() == "Add [mqtt]"]

    click(qtbot, add)

    assert window.document.has_section("mqtt")
    assert row(window, "host", "mqtt").error.text() == "Field required"
    password = row(window, "password", "mqtt")
    assert password.line.echoMode() == QLineEdit.EchoMode.Password
    type_into(qtbot, password.line, "secret")
    assert window.document.get(("mqtt", "password")) == "secret"
    reveal = next(button for button in password.findChildren(QToolButton) if button.isCheckable())
    click(qtbot, reveal)
    assert password.line.echoMode() == QLineEdit.EchoMode.Normal

    (remove,) = [button for button in page.findChildren(QPushButton) if button.text() == "Remove [mqtt]"]
    click(qtbot, remove)
    assert not window.document.has_section("mqtt")


def test_a_file_is_chosen_with_a_dialog(qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    window.document.add_section("mqtt")
    window.reload_pages()
    password_file = row(window, "password_file", "mqtt")
    browse = next(button for button in password_file.findChildren(QToolButton) if button.toolTip() == "Choose the file")
    chosen = [str(Path.home() / ".mqtt-password"), "", "/etc/mqtt-password"]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (chosen.pop(0), ""))

    click(qtbot, browse)
    assert window.document.get(("mqtt", "password_file")) == "~/.mqtt-password"
    click(qtbot, browse)
    assert window.document.get(("mqtt", "password_file")) == "~/.mqtt-password"
    click(qtbot, browse)
    assert window.document.get(("mqtt", "password_file")) == "/etc/mqtt-password"


def test_aliases_are_edited(qtbot: QtBot, window: MainWindow):
    page = window.pages["aliases"]
    assert isinstance(page, AliasesPage)
    (name, alias) = page.edits[0]
    assert (name.text(), alias.text()) == ("WEBRTC VoiceEngine", "Discord")

    (add,) = [button for button in page.findChildren(QPushButton) if button.text() == "Add alias"]
    click(qtbot, add)
    assert window.document.aliases == [("WEBRTC VoiceEngine", "Discord"), ("", "")]
    new_name, new_alias = page.edits[1]
    assert new_name.property("problem") is True
    assert page.problem.text() == "'': the name of the application is missing"

    menu_button = [button for button in page.findChildren(QToolButton) if button.menu()][1]
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    menu.actions()[0].trigger()
    type_into(qtbot, new_alias, "Browser")
    assert window.document.aliases[1] == ("Brave", "Browser")

    remove = [button for button in page.findChildren(QToolButton) if button.toolTip() == "Remove the alias"]
    click(qtbot, remove[0])
    assert window.document.aliases == [("Brave", "Browser")]


# -- the service and the file -------------------------------------------------------------------------------------


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
    monkeypatch.setattr(window_module, "executable", lambda: "/opt/xtouch-daemon")
    systemctl.properties = properties
    window = make_window()
    assert (window.pill.text(), window.pill.property("tone"), window.service_button.text()) == (pill, tone, button)
    isolated.answer = QMessageBox.StandardButton.Yes

    click(qtbot, window.service_button)

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
    click(qtbot, window.service_button)

    assert systemctl.commands[shows:] == []
    assert not (tmp_path / "systemd").exists()
    assert window.status.text() == ""


def test_keys_typed_into_a_new_window_do_not_press_the_service_button(window: MainWindow):
    assert window.service_button.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_a_failing_systemctl_is_reported(qtbot: QtBot, make_window: MakeWindow, systemctl, isolated: Dialogs):
    window = make_window()

    def fail(command: list[str]) -> str:
        raise ServiceError("systemctl --user restart failed: nope")

    window.service._run = fail
    click(qtbot, window.service_button)
    assert isolated.shown == ["systemctl --user restart failed: nope"]
    assert window.pill.text() == "unavailable"
    assert window.service_button.isHidden()


def test_a_changed_device_offers_a_restart(qtbot: QtBot, window: MainWindow, systemctl: FakeSystemctl):
    window.document.set(("device", "name"), "Other")
    window.refresh()

    assert window.save()
    assert not window.restart_button.isHidden()

    click(qtbot, window.restart_button)
    assert systemctl.commands[-2] == ["systemctl", "--user", "restart", UNIT_NAME]
    assert window.status.text() == "Restarted the service."


def test_a_changed_mqtt_section_offers_a_restart_instead_of_a_reload(window: MainWindow, daemon: RecordingInstance):
    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.refresh()

    assert window.save()

    assert daemon.reloads == []
    assert window.status.text() == "Saved. The [mqtt] section changed: restart the service to use the configuration."
    assert not window.restart_button.isHidden()


def test_a_failing_restart_or_reload_is_reported(
    qtbot: QtBot, window: MainWindow, systemctl: FakeSystemctl, isolated: Dialogs
):
    window.document.set(("device", "name"), "Other")
    window.refresh()
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
    window.refresh()
    assert window.save()
    assert window.status.text() == "Saved, but reloading the service failed: [Errno 3] No such process"


def test_a_daemon_started_elsewhere_is_shown_and_reloaded(qtbot: QtBot, make_window: MakeWindow, path: Path):
    daemon = RecordingInstance(4242, path.resolve(), systemd=False)
    window = make_window(find_daemon=lambda: daemon)

    assert (window.pill.text(), window.pill.property("tone")) == ("running elsewhere", "good")
    assert "process 4242" in window.pill.toolTip()
    assert window.service_button.isHidden()

    window.document.set(("device", "name"), "Other")
    window.refresh()
    assert window.save()

    assert daemon.reloads == [4242]
    assert window.status.text().endswith("restart the daemon (process 4242) for that to take effect.")
    # the window restarts only the service
    assert window.restart_button.isHidden()


def test_without_a_daemon_saving_only_saves(make_window: MakeWindow, systemctl: FakeSystemctl):
    systemctl.properties = STOPPED
    window = make_window(find_daemon=lambda: None)
    window.document.set(("device", "name"), "Other")
    window.refresh()

    assert window.save()

    assert window.status.text() == "Saved. The daemon is not running: start it to use the configuration."
    assert window.restart_button.isHidden()


def test_saving_what_did_not_change_does_nothing(window: MainWindow, path: Path):
    before = path.stat().st_mtime_ns
    assert window.save()
    assert path.stat().st_mtime_ns == before


def test_a_file_that_can_not_be_written_is_reported(window: MainWindow, path: Path, isolated: Dialogs):
    window.document.set(("behavior", "max_volume"), 110)
    window.refresh()
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
    assert tomllib.loads((tmp_path / "new.toml").read_text())["strip"][0] == {"type": "auto", "color": "cyan"}
    assert window.status.text().startswith("Saved. The service reads")


def test_revert_drops_the_changes(qtbot: QtBot, window: MainWindow):
    window.document.remove_strip(0)
    window.refresh()

    click(qtbot, window.revert_button)

    assert len(window.document.strips) == 2
    assert window.status.text() == "Reverted to the file."


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
    window.refresh()
    isolated.answer = answer

    assert window.close() == closed
    assert isolated.shown == ["Save the changes before closing?"]
    assert ("max_volume = 110" in path.read_text()) == saved
    isolated.answer = QMessageBox.StandardButton.Discard


def test_closing_without_changes_does_not_ask(window: MainWindow, isolated: Dialogs):
    assert window.close()
    assert isolated.shown == []


def test_the_theme_switches_and_is_remembered(qtbot: QtBot, window: MainWindow):
    click(qtbot, window.theme_button)
    assert theme.current_mode() == theme.ThemeMode.LIGHT
    assert theme.load_theme_mode() == theme.ThemeMode.LIGHT

    click(qtbot, window.theme_button)
    assert theme.load_theme_mode() == theme.ThemeMode.DARK
    QSettings().setValue("theme", "purple")
    assert theme.load_theme_mode() == theme.ThemeMode.DARK


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
    # Ctrl+C closes the window like its close button
    handlers[signal.SIGINT](signal.SIGINT, None)
    assert closed == [True]
    shown[0].deleteLater()


def test_a_homeassistant_strip_has_its_id_as_placeholder(window: MainWindow):
    window.document.add_section("mqtt")
    window.document.set_strip_type(1, "homeassistant")
    window.select(1)

    assert row(window, "id").line.placeholderText() == "strip_2"
    assert window.preview.strips[1].look.detail.startswith("entities of Home Assistant (strip_<position>)")


def test_help_shows_quotes_and_code_as_they_are_meant(window: MainWindow):
    # the help of the label has quotes but no tag, which Qt would show as plain text, entities and all
    (help_label,) = [
        widget for widget in row(window, "label").findChildren(QLabel) if "start of the device" in widget.text()
    ]
    assert help_label.textFormat() == Qt.TextFormat.RichText
    document = QTextDocument()
    document.setHtml(help_label.text())
    assert '"Output"' in document.toPlainText()
    assert "&quot;" not in document.toPlainText()
