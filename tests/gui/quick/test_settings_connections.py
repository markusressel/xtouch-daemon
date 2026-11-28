"""The connection tests of the page Settings (the broker) and the plugin installers of the voice chat clients."""

from pathlib import Path

import pytest

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.forms_host import settings
from tests.support.quick import Ui
from xtouch_daemon.config.sections import MqttConfig
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.voip import CLIENTS, MUMBLE, NO_PLUGIN, TEAMSPEAK, ClientSetup, PluginSetup
from xtouch_daemon.gui.quick.pages.settings_support import BrokerTester, PluginInstaller
from xtouch_daemon.voip import mumble, teamspeak


def with_mqtt(ui: Ui, host: str | None = "broker") -> None:
    settings(ui).showSection("mqtt")
    ui.app.editor.add_section("mqtt")
    if host is not None:
        ui.app.editor.document.set(("mqtt", "host"), host)
        ui.app.editor.edited()
    ui.settle()


def test_the_broker_can_be_tried_before_the_settings_are_saved(make_ui: MakeUi):
    tried: list[MqttConfig] = []

    async def works(config: MqttConfig) -> Status:
        tried.append(config)
        return Status(f"Connected to {config.host}:{config.port}: these settings work.", Tone.GOOD)

    ui = make_ui(try_broker=works)
    assert not ui.shows("test_mqtt")
    with_mqtt(ui)
    assert ui.shows("test_mqtt")
    ui.click("test_mqtt")
    ui.wait_until(lambda: ui.shows("test_result_mqtt"))
    ui.wait_until(lambda: ui.text("test_result_mqtt") == "Connected to broker:1883: these settings work.")
    assert [config.host for config in tried] == ["broker"]
    # unsaved: the editor's settings, not the file's
    assert ui.app.editor.document.modified
    assert ui.item("test_mqtt").property("enabled") is True


def test_settings_with_problems_are_not_tried(make_ui: MakeUi):
    async def never(config: MqttConfig) -> Status:
        raise AssertionError("not tried")

    ui = make_ui(try_broker=never)
    settings(ui).showSection("mqtt")
    ui.app.editor.add_section("mqtt")
    ui.app.editor.document.set(("mqtt", "port"), "many")
    ui.app.editor.edited()
    ui.settle()
    ui.click("test_mqtt")
    assert ui.text("test_result_mqtt") == "Fix the problems of the settings first."


def test_a_failed_test_says_what_to_check(ui: Ui):
    with_mqtt(ui)
    ui.click("test_mqtt")
    ui.wait_until(lambda: "Connection refused" in ui.text("test_result_mqtt"))


def test_a_result_after_the_section_was_removed_has_nowhere_to_go(ui: Ui):
    with_mqtt(ui)
    ui.app.editor.remove_section("mqtt")
    ui.settle()
    section = settings(ui).sections["mqtt"]
    section.tester.finished.emit(Status("late", Tone.GOOD))
    ui.app.editor.add_section("mqtt")
    ui.settle()
    assert section.live.view["test"] is None


def test_the_daemons_connection_shows_in_a_pill(ui: Ui):
    with_mqtt(ui)
    assert ui.text("live_mqtt") == "unknown"


@pytest.mark.parametrize(("client", "error"), [(MUMBLE, mumble.MumbleError), (TEAMSPEAK, teamspeak.TeamSpeakError)])
def test_the_plugin_is_installed_with_a_click(
    client: ClientSetup, error: type[Exception], make_ui: MakeUi, tmp_path: Path
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
    ui = make_ui(
        plugin_installers=[
            PluginInstaller(client, install, lambda: setups[-1]),
            PluginInstaller(other, lambda: "", lambda: NO_PLUGIN),
        ]
    )
    settings(ui).showSection("voip")
    ui.settle()
    name = client.name.lower()
    assert ui.item(f"install_{name}").property("enabled") is True
    assert ui.text(f"plugin_result_{name}") == ""

    ui.click(f"install_{name}")
    ui.wait_until(lambda: ui.text(f"plugin_result_{name}").startswith("Installed into"))
    assert installs == ["install"]
    assert ui.item(f"install_{name}").property("enabled") is True

    ui.click(f"install_{name}")
    ui.wait_until(lambda: ui.text(f"plugin_result_{name}") == "cmake --build failed: boom")
    # the result stays when the document changes
    ui.app.editor.edited()
    ui.settle()
    assert ui.text(f"plugin_result_{name}") == "cmake --build failed: boom"


def test_a_client_that_is_not_installed_has_no_install_button(make_ui: MakeUi):
    ui = make_ui()
    settings(ui).showSection("voip")
    ui.settle()
    assert ui.shows("plugin_pill_mumble")
    assert ui.shows("plugin_steps_teamspeak")


# -- the threads ----------------------------------------------------------------------------------------------------


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


def test_an_install_ends_with_its_message_and_uses_the_clients_own_setup_by_default():
    results: list[Status] = []
    installer = PluginInstaller(TEAMSPEAK, lambda: "done", lambda: NO_PLUGIN)
    installer.finished.connect(results.append)
    installer._run()  # pyright: ignore[reportPrivateUsage]
    assert results == [Status("done", Tone.GOOD)]
    assert PluginInstaller(MUMBLE).setup == MUMBLE.setup
