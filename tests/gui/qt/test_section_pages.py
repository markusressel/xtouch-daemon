"""
The pages of the sections, with testing the broker and installing the Mumble plugin.
"""

import dataclasses
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
)
from pytestqt.qtbot import QtBot

from tests.support.gui import NO_MUMBLE, FakeLiveDaemon, MakeWindow, click, row, shows, snapshot, strip_state, type_into
from xtouch_daemon.config.sections import MqttConfig
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.qt.pages.aliases import AliasesPage
from xtouch_daemon.gui.qt.pages.sections import MumbleInstaller, SectionPage
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import MqttState, SlotsState, SlotView, VoipState
from xtouch_daemon.voip import mumble


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
    window.editor.edited()
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
    # undo and redo show as many lines as there are aliases
    window.editor.undo()
    assert len(page.edits) == 2
    window.editor.redo()
    assert len(page.edits) == 1
    assert page.edits[0][1].text() == "Browser"


def test_the_connection_to_home_assistant_shows_while_the_daemon_uses_it(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.editor.edited()
    window.save()
    window.show_page("mqtt")
    page = window.mqtt_page
    assert page.box is not None
    # the daemon runs without [mqtt]: it reads it when it starts
    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: page.box is not None and page.box.live_pill.text() == "not in use")
    assert window.mqtt_pill.isHidden()

    refused = MqttState("broker:1883", None, False, False, "[code:5] Connection refused: Not authorised", 4)
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), mqtt=False, mqtt_state=refused))
    qtbot.waitUntil(lambda: window.mqtt_pill.text() == "Home Assistant · not authorized")
    assert not window.mqtt_pill.isHidden()
    assert "check <code>username</code>" in page.box.live_detail.text()

    # the pill leads to the settings
    window.show_page("behavior")
    qtbot.mouseClick(window.mqtt_pill, Qt.MouseButton.LeftButton)
    assert window.current_page == "mqtt"

    connected = dataclasses.replace(refused, connected=True, ready=True, error=None)
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), mqtt=True, mqtt_state=connected))
    qtbot.waitUntil(lambda: window.mqtt_pill.text() == "Home Assistant")
    assert page.box.live_pill.text() == "connected"


def test_the_settings_of_home_assistant_can_be_tried_before_they_are_saved(qtbot: QtBot, make_window: MakeWindow):
    tried: list[MqttConfig] = []

    async def works(config: MqttConfig) -> Status:
        tried.append(config)
        return Status(f"Connected to {config.host}:{config.port}: these settings work.", Tone.GOOD)

    window = make_window(test_broker=works)
    page = window.mqtt_page
    # nothing to try without the section
    assert not shows(page.box, page)
    window.show_page("mqtt")
    window.document.add_section("mqtt")
    window.editor.edited()
    box = page.box
    assert box is not None
    assert box.live_pill.text() == "unknown"

    # the settings miss the host
    click(qtbot, box.test_button)
    assert box.test_result.text() == "Fix the problems of the settings first."
    assert tried == []

    window.document.set(("mqtt", "host"), "broker")
    click(qtbot, box.test_button)
    qtbot.waitUntil(lambda: box.test_result.text() == "Connected to broker:1883: these settings work.")
    assert box.test_button.isEnabled()
    assert box.test_hint.isHidden()
    # unsaved: the editor's settings, not the file's
    assert window.document.modified
    assert [config.host for config in tried] == ["broker"]

    # the result stays when the page is built again
    window.editor.edited()
    assert page.box is not None
    assert page.box.test_result.text() == "Connected to broker:1883: these settings work."


def test_a_failed_test_says_what_to_check(qtbot: QtBot, window: MainWindow):
    window.show_page("mqtt")
    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.editor.edited()
    box = window.mqtt_page.box
    assert box is not None
    click(qtbot, box.test_button)
    qtbot.waitUntil(lambda: "Connection refused" in box.test_result.text())
    assert box.test_hint.text() == "Is it running?"
    assert not box.test_hint.isHidden()

    # a result that comes after the section was removed has nowhere to go
    window.document.remove_section("mqtt")
    window.editor.edited()
    window.mqtt_page.tester.finished.emit(Status("late", Tone.GOOD))
    page = window.mqtt_page
    assert not shows(page.box, page)
    # nor does it show once the section is back
    window.editor.add_section("mqtt")
    assert page.box.test_result.isHidden()


def test_the_voice_chat_page_tells_whether_mumble_is_connected(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    window.show_page("voip")
    box = window.voip_page.box
    assert box.live_pill.text() == "unknown"
    # neither a plugin nor Mumble on this machine: nothing to install, the steps say what to do
    assert not box.install_button.isEnabled()
    assert "Mumble is not installed" in box.install_button.toolTip()
    assert "Reload plugins" in box.steps.text()
    assert "integrations/mumble/" in box.steps.text()

    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: box.live_pill.text() == "not in use")
    for voip, text, tip in [
        (VoipState("demo", True, None, None, 5), "demo", "made up"),
        (VoipState("bridge", False, None, None, 0), "waiting for Mumble", "enable the plugin"),
        (VoipState("bridge", True, "mumble", "Lobby", 1), "Mumble connected", "1 person in Lobby."),
        (VoipState("bridge", True, None, None, 3), "A client connected", "3 people."),
    ]:
        live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), voip=voip))
        qtbot.waitUntil(lambda text=text: box.live_pill.text() == text)
        assert tip in box.live_detail.text()


def test_the_voice_chat_page_shows_the_plugin_without_the_section(make_window: MakeWindow):
    # voip strips use the defaults of [voip] without it, so the voice chat is there all the same
    window = make_window()
    window.show_page("voip")
    page = window.voip_page
    assert not window.document.has_section("voip")
    assert shows(page.box, page)
    assert shows(page.absent, page)
    note = page.absent.findChild(QLabel)
    assert note is not None
    assert "voip strips use its defaults" in note.text()

    window.editor.add_section("voip")
    assert shows(page.box, page)
    assert not shows(page.absent, page)


def test_the_mumble_plugin_is_installed_with_a_click(qtbot: QtBot, make_window: MakeWindow, tmp_path: Path):
    installs: list[str] = []
    setups = [mumble.Setup(None, True, None, True)]

    def install() -> str:
        installs.append("install")
        if len(installs) > 1:
            raise mumble.MumbleError("cmake --build failed: boom")
        setups.append(mumble.Setup(tmp_path / "b.mumble_plugin", True, tmp_path / "libxtouch-daemon.so", True))
        return "Installed into the plugin directory."

    window = make_window(mumble_installer=MumbleInstaller(install, lambda: setups[-1]))
    window.show_page("voip")
    box = window.voip_page.box
    assert box.install_button.isEnabled()
    assert (
        box.install_button.toolTip()
        == 'Builds the plugin, then copies it into Mumble\'s plugin directory; then Mumble needs "Reload plugins".'
    )
    assert box.result.isHidden()

    click(qtbot, box.install_button)
    qtbot.waitUntil(lambda: box.result.text().startswith("Installed into"))
    assert installs == ["install"]
    assert box.install_button.isEnabled()
    assert box.install_button.toolTip() == (
        'Copies it into Mumble\'s plugin directory; then Mumble needs "Reload plugins".'
    )
    assert "Mumble has the plugin" in box.steps.text()

    click(qtbot, box.install_button)
    qtbot.waitUntil(lambda: box.result.text() == "cmake --build failed: boom")
    assert box.result.property("role") == "error"
    # the result stays when the document is shown again
    window.editor.edited()
    assert window.voip_page.box.result.text() == "cmake --build failed: boom"


def test_the_installer_runs_in_a_thread():
    results: list[Status] = []
    installer = MumbleInstaller(lambda: "done", lambda: NO_MUMBLE)
    installer.finished.connect(results.append)
    installer._run()  # pyright: ignore[reportPrivateUsage]
    assert results == [Status("done", Tone.GOOD)]
    assert installer.setup() == NO_MUMBLE


def test_the_mode_of_a_daemon_with_slots_shows_next_to_the_preview(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    assert window.slots_pill.isHidden()
    slots = SlotsState("gaming", None, (SlotView(1, 0, "game", None, None, ()),), (), {})
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), slots=slots))
    qtbot.waitUntil(lambda: window.slots_pill.text() == "Mode gaming")
    assert not window.slots_pill.isHidden()
    assert "slot 1: game" in window.slots_pill.toolTip()
