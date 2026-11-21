"""
The pages of the sections, with testing the broker and installing the Mumble plugin.
"""

import dataclasses
from pathlib import Path

import pytest
from PyQt6.QtWidgets import (
    QFileDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.support.gui import (
    FakeLiveDaemon,
    MakeWindow,
    buttons,
    click,
    pill,
    plain,
    row,
    show_channel,
    shows,
    snapshot,
    strip_state,
    type_into,
)
from xtouch_daemon.config.sections import MqttConfig
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.voip import CLIENTS, MUMBLE, NO_PLUGIN, TEAMSPEAK, ClientSetup, PluginSetup
from xtouch_daemon.gui.qt.fields.basics import _HELP_PROPERTY as HELP_PROPERTY  # pyright: ignore[reportPrivateUsage]
from xtouch_daemon.gui.qt.fields.basics import help_html
from xtouch_daemon.gui.qt.fields.names import completer_of
from xtouch_daemon.gui.qt.pages.aliases import AliasesPage
from xtouch_daemon.gui.qt.pages.sections import BrokerTester, PluginInstaller, SectionPage
from xtouch_daemon.gui.qt.theme.tokens import ThemeMode
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import MqttState, SlotsState, SlotView, VoipClient, VoipState
from xtouch_daemon.voip import mumble, teamspeak


def test_the_parts_that_do_not_show_are_in_the_window_and_follow_the_theme(window: MainWindow):
    # [mqtt] is not in the file: its options don't show
    page = window.pages["mqtt"]
    assert isinstance(page, SectionPage)
    assert page.present.isHidden()
    show_channel(window, "browser")
    show_channel(window, "out")
    hidden = [page.present, window.channels_page.form_widgets["apps"]]
    assert all(QWidget.isAncestorOf(window, part) for part in hidden)

    window.set_theme(ThemeMode.LIGHT)

    helps = [
        (label, source)
        for part in hidden
        for label in part.findChildren(QLabel)
        if (source := label.property(HELP_PROPERTY)) is not None
    ]
    assert helps
    assert all(label.text() == help_html(*source) for label, source in helps)


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
    # a line without a name stays in the window until it has one
    assert window.document.get(("aliases",)) == {"WEBRTC VoiceEngine": "Discord"}
    new_name, new_alias = page.edits[1]
    assert new_name.property("problem") is True
    assert page.problem.text() == "'': the name of the application is missing"

    completer = completer_of(new_name)
    assert completer is not None
    # the applications that play, picked from the list
    completer.activated.emit("Brave")
    type_into(qtbot, new_alias, "Browser")
    assert window.document.get(("aliases",)) == {"WEBRTC VoiceEngine": "Discord", "Brave": "Browser"}
    type_into(qtbot, new_name, "WEBRTC VoiceEngine")
    assert page.problem.text() == "'WEBRTC VoiceEngine': twice, the file keeps the first"
    type_into(qtbot, new_name, "Brave")

    remove = [button for button in page.findChildren(QToolButton) if button.toolTip() == "Remove the alias"]
    click(qtbot, remove[0])
    assert window.document.get(("aliases",)) == {"Brave": "Browser"}
    # the last one: no [aliases] left
    remove = buttons(page, QToolButton, lambda button: button.toolTip() == "Remove the alias")
    click(qtbot, remove[0])
    assert not window.document.has_section("aliases")
    window.editor.undo()
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

    refused = MqttState("broker:1883", None, False, False, "[code:5] Connection refused: Not authorised", 4)
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), mqtt=False, mqtt_state=refused))
    qtbot.waitUntil(lambda: page.box is not None and page.box.live_pill.text() == "not authorized")
    assert "check <code>username</code>" in page.box.live_detail.text()

    connected = dataclasses.replace(refused, connected=True, ready=True, error=None)
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), mqtt=True, mqtt_state=connected))
    qtbot.waitUntil(lambda: page.box is not None and page.box.live_pill.text() == "connected")


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


def test_the_voice_chat_page_tells_whether_each_plugin_is_connected(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    found = PluginSetup(None, True, None, True)
    window = make_window(
        live_socket=live_daemon.path,
        plugin_installers=[PluginInstaller(client, lambda: "", lambda: found) for client in CLIENTS],
    )
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    window.show_page("voip")
    mumble_box, teamspeak_box = window.voip_page.boxes
    assert mumble_box.live_pill.text() == teamspeak_box.live_pill.text() == "unknown"
    assert "Reload plugins" in mumble_box.steps.text()
    assert "guides/mumble/" in mumble_box.steps.text()
    assert "Tools, Options, Addons" in teamspeak_box.steps.text()
    assert "guides/teamspeak/" in teamspeak_box.steps.text()
    assert teamspeak_box.install_button.text() == "Install TeamSpeak plugin"

    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: mumble_box.live_pill.text() == "not in use")
    for voip, mumble_text, teamspeak_text, tip in [
        (VoipState("demo", True, None, None, 5), "demo", "demo", "made up"),
        (VoipState("bridge", False, None, None, 0), "waiting for Mumble", "waiting for TeamSpeak", "enable the plugin"),
        (VoipState("bridge", True, "mumble", "Lobby", 1), "Mumble connected", "not connected", "1 person in Lobby."),
        (VoipState("bridge", True, "teamspeak", "Lobby", 2), "not connected", "TeamSpeak connected", "2 people"),
        # several plugins, as a daemon with one plugin per client tells them
        (
            VoipState(
                "bridge",
                True,
                "mumble, teamspeak",
                "Lobby",
                3,
                clients=(VoipClient("mumble", "Lobby"), VoipClient("teamspeak")),
            ),
            "Mumble connected",
            "TeamSpeak connected",
            "3 people: Mumble in Lobby, TeamSpeak.",
        ),
        (VoipState("bridge", True, None, None, 3), "not connected", "not connected", "A client connected: 3 people."),
    ]:
        live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), voip=voip))
        qtbot.waitUntil(
            lambda mumble_text=mumble_text, teamspeak_text=teamspeak_text: (
                (
                    mumble_box.live_pill.text(),
                    teamspeak_box.live_pill.text(),
                )
                == (mumble_text, teamspeak_text)
            )
        )
        assert tip in plain(mumble_box.live_detail.text())


def test_a_client_that_is_not_installed_gets_a_line(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon):
    # neither a plugin nor a client on this machine
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    window.show_page("voip")
    page = window.voip_page
    for box, hint in zip(page.boxes, ["Mumble is not installed", "TeamSpeak is not installed"], strict=True):
        assert box.live_pill.text() == "not installed"
        assert not shows(box.install_button, page)
        assert not shows(box.live_detail, page)
        assert hint in box.steps.text()
        assert "Set up the plugin once" not in box.steps.text()
    # its plugin connects all the same (e.g. a client of its own): the box shows it, with the steps
    live_daemon.send(
        dataclasses.replace(snapshot(window, strip_state()), voip=VoipState("bridge", True, "teamspeak", "Lobby", 1))
    )
    teamspeak_box = page.boxes[1]
    qtbot.waitUntil(lambda: teamspeak_box.live_pill.text() == "TeamSpeak connected")
    assert "Set up the plugin once" in teamspeak_box.steps.text()
    assert not teamspeak_box.install_button.isEnabled()
    assert page.boxes[0].live_pill.text() == "not installed"


def test_the_voice_chat_page_shows_the_plugin_without_the_section(make_window: MakeWindow):
    # voip strips use the defaults of [voip] without it, so the voice chat is there all the same
    window = make_window()
    window.show_page("voip")
    page = window.voip_page
    assert not window.document.has_section("voip")
    assert all(shows(box, page) for box in page.boxes)
    assert shows(page.absent, page)
    note = page.absent.findChild(QLabel)
    assert note is not None
    assert "voip strips use its defaults" in note.text()

    window.editor.add_section("voip")
    assert all(shows(box, page) for box in page.boxes)
    assert not shows(page.absent, page)


@pytest.mark.parametrize(
    ("client", "error", "target", "reload"),
    [
        (MUMBLE, mumble.MumbleError, "Mumble's plugin directory", '"Reload plugins"'),
        (TEAMSPEAK, teamspeak.TeamSpeakError, "~/.ts3client/plugins", '"Reload All" in Tools, Options, Addons'),
    ],
)
def test_the_plugin_is_installed_with_a_click(
    client: ClientSetup,
    error: type[Exception],
    target: str,
    reload: str,
    qtbot: QtBot,
    make_window: MakeWindow,
    tmp_path: Path,
):
    installs: list[str] = []
    setups = [PluginSetup(None, True, None, True)]

    def install() -> str:
        installs.append("install")
        if len(installs) > 1:
            raise error("cmake --build failed: boom")
        setups.append(PluginSetup(tmp_path / "plugin", True, tmp_path / "installed.so", True))
        return "Installed into the plugin directory."

    other = next(each for each in CLIENTS if each != client)
    window = make_window(
        plugin_installers=[
            PluginInstaller(client, install, lambda: setups[-1]),
            PluginInstaller(other, lambda: "", lambda: NO_PLUGIN),
        ]
    )
    window.show_page("voip")
    box = window.voip_page.boxes[0]
    assert box.install_button.isEnabled()
    assert (
        box.install_button.toolTip()
        == f"Builds the plugin, then copies it into {target}; then {client.name} needs {reload}."
    )
    assert box.result.isHidden()

    click(qtbot, box.install_button)
    qtbot.waitUntil(lambda: box.result.text().startswith("Installed into"))
    assert installs == ["install"]
    assert box.install_button.isEnabled()
    assert box.install_button.toolTip() == f"Copies it into {target}; then {client.name} needs {reload}."
    assert f"{client.name} has the plugin" in box.steps.text()

    click(qtbot, box.install_button)
    qtbot.waitUntil(lambda: box.result.text() == "cmake --build failed: boom")
    assert box.result.property("role") == "error"
    # the result stays when the document is shown again
    window.editor.edited()
    assert window.voip_page.boxes[0].result.text() == "cmake --build failed: boom"


def test_a_test_of_the_broker_always_ends_and_only_the_latest_one_shows():
    results: list[Status] = []

    async def broken(config: MqttConfig) -> Status:
        raise RuntimeError("no loop")

    tester = BrokerTester(broken)
    tester.finished.connect(results.append)
    tester.started = 1
    tester._run(MqttConfig(host="broker"), 1)  # pyright: ignore[reportPrivateUsage]
    assert results == [Status("Can't connect: RuntimeError: no loop.", Tone.BAD)]

    async def works(config: MqttConfig) -> Status:
        return Status(config.host, Tone.GOOD)

    tester = BrokerTester(works)
    tester.finished.connect(results.append)
    # a second test started before the first one ended: the first result is old
    tester.started = 2
    tester._run(MqttConfig(host="first"), 1)  # pyright: ignore[reportPrivateUsage]
    tester._run(MqttConfig(host="second"), 2)  # pyright: ignore[reportPrivateUsage]
    assert results[1:] == [Status("second", Tone.GOOD)]


def test_an_install_that_fails_in_any_way_ends_with_it():
    results: list[Status] = []

    def broken() -> str:
        raise PermissionError("read-only")

    installer = PluginInstaller(TEAMSPEAK, broken, lambda: NO_PLUGIN)
    installer.finished.connect(results.append)
    installer._run()  # pyright: ignore[reportPrivateUsage]
    assert results == [Status("The setup failed: PermissionError: read-only.", Tone.BAD)]


def test_the_installer_runs_in_a_thread():
    results: list[Status] = []
    installer = PluginInstaller(TEAMSPEAK, lambda: "done", lambda: NO_PLUGIN)
    installer.finished.connect(results.append)
    installer._run()  # pyright: ignore[reportPrivateUsage]
    assert results == [Status("done", Tone.GOOD)]
    assert installer.setup() == NO_PLUGIN
    # by default the client's own
    assert PluginInstaller(MUMBLE).setup == MUMBLE.setup


def test_the_mode_of_a_daemon_with_slots_shows_next_to_the_preview(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    pill_of_mode = window.device_view.slots_pill
    assert pill_of_mode.isHidden()
    slots = SlotsState("gaming", None, (SlotView(1, 0, "game", None, None, ()),), (), {})
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), slots=slots))
    qtbot.waitUntil(lambda: pill(pill_of_mode) == "Mode: gaming")
    assert not pill_of_mode.isHidden()
    assert "The rules pick it now." in pill_of_mode.toolTip()
