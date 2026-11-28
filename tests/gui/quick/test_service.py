"""
The service and the file in the window in Qt Quick: installing, starting and stopping the service, saving and
applying, closing with unsaved changes.
"""

import dataclasses
import tomllib
from pathlib import Path

import pytest
from PyQt6.QtCore import QObject, Qt

from tests.gui.quick.conftest import MakeUi
from tests.support.dialogs import FakeDialogs
from tests.support.gui import MISSING, RUNNING, STOPPED, FakeLiveDaemon, strip_state
from tests.support.instance import RecordingInstance
from tests.support.packaging import install_package
from tests.support.quick import Ui
from tests.support.systemd import FakeSystemctl
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.qt.fields.popover import Entry
from xtouch_daemon.gui.quick.window import service as service_module
from xtouch_daemon.gui.quick.window.dialogs import CANCEL, DISCARD, SAVE, YES
from xtouch_daemon.gui.quick.window.service import ServiceBackend
from xtouch_daemon.system import systemd
from xtouch_daemon.system.systemd import UNIT_NAME, ServiceError, unit_file, unit_path

CHECKOUT = "/home/me/xtouch-daemon/.venv/bin/xtouch-daemon"


def controls(ui: Ui) -> ServiceBackend:
    return ui.app.shell._controls  # pyright: ignore[reportPrivateUsage]


def popup(ui: Ui, name: str) -> QObject:
    """A popup of the window by its `objectName` (a popup is no item: it is a child of the item it is declared in)."""
    for item in ui.all_items():
        for child in item.children():
            if child.objectName() == name:
                return child
    raise AssertionError(f"no popup named {name!r}")


def entries(ui: Ui) -> list[Entry]:
    """The rows of the popover of the service pill (built as when it opens)."""
    popover = controls(ui).details
    popover.refresh()
    return [entry for entry in popover._content.entries if isinstance(entry, Entry)]  # pyright: ignore[reportPrivateUsage]


def details(ui: Ui, title: str) -> Entry | None:
    return next((entry for entry in entries(ui) if entry.title == title), None)


def actions(ui: Ui, title: str = "Service") -> list[str]:
    entry = details(ui, title)
    return [text for text, _ in entry.actions] if entry is not None else []


def do(ui: Ui, text: str, title: str = "Service") -> None:
    """Presses the button `text` of the row `title` in the popover of the service pill."""
    entry = details(ui, title)
    assert entry is not None
    dict(entry.actions)[text]()
    ui.settle()


def status(ui: Ui) -> str:
    return ui.app.shell.statusText


def unit_properties(state: str, unit: Path, program: str) -> str:
    """`systemctl show` of a service with its unit file and the program it starts."""
    return f"{state}FragmentPath={unit}\nExecStart={{ path={program} ; argv[]={program} run ; ignore_errors=no }}\n"


def write_user_unit() -> None:
    unit_path().parent.mkdir(parents=True)
    unit_path().write_text(unit_file(CHECKOUT))


@pytest.mark.parametrize(
    ("properties", "pill", "tone", "button", "command"),
    [
        (MISSING, "not installed", "warn", "Install and start", ["systemctl", "--user", "daemon-reload"]),
        (STOPPED, "stopped", "neutral", "Start", ["systemctl", "--user", "enable", "--now", "--no-block", UNIT_NAME]),
        (RUNNING, "running", "good", "Restart", ["systemctl", "--user", "restart", "--no-block", UNIT_NAME]),
    ],
)
def test_the_service_is_shown_and_controlled(
    make_ui: MakeUi,
    systemctl: FakeSystemctl,
    dialogs: FakeDialogs,
    monkeypatch: pytest.MonkeyPatch,
    properties: str,
    pill: str,
    tone: str,
    button: str,
    command: list[str],
):
    monkeypatch.setattr(service_module, "executable", lambda: "/opt/xtouch-daemon")
    systemctl.properties = properties
    ui = make_ui()
    assert (ui.text("service_pill"), ui.item("service_pill").property("tone")) == (pill, tone)
    # what needs doing is next to the pill; Restart of a running service is in the popover only
    assert ui.shows("service_button") is (properties != RUNNING)
    if properties != RUNNING:
        assert ui.text("service_button") == button
    dialogs.answer = YES

    do(ui, button)

    assert command in systemctl.commands
    assert status(ui).endswith("the service…")
    # installing and starting ask first, a restart of the running service doesn't
    assert len(dialogs.shown) == (0 if properties == RUNNING else 1)


def test_the_button_next_to_the_pill_does_the_same(make_ui: MakeUi, systemctl: FakeSystemctl, dialogs: FakeDialogs):
    systemctl.properties = STOPPED
    ui = make_ui()
    dialogs.answer = YES

    ui.click("service_button")

    assert ["systemctl", "--user", "enable", "--now", "--no-block", UNIT_NAME] in systemctl.commands
    assert status(ui) == "Starting the service…"
    # the key typed into a new window must not press it
    assert ui.item("service_button").property("focusPolicy") == Qt.FocusPolicy.NoFocus


@pytest.mark.parametrize("properties", [MISSING, STOPPED])
def test_a_service_is_installed_or_started_only_when_confirmed(
    make_ui: MakeUi, systemctl: FakeSystemctl, tmp_path: Path, dialogs: FakeDialogs, properties: str
):
    systemctl.properties = properties
    ui = make_ui()
    shows = len(systemctl.commands)

    dialogs.answer = "no"
    ui.click("service_button")

    assert systemctl.commands[shows:] == []
    assert not (tmp_path / "systemd").exists()
    assert status(ui) == ""


@pytest.mark.parametrize(("properties", "stop"), [(RUNNING, True), (STOPPED, False), (MISSING, False)])
def test_only_a_running_service_can_be_stopped(make_ui: MakeUi, systemctl: FakeSystemctl, properties: str, stop: bool):
    systemctl.properties = properties

    ui = make_ui()

    assert ("Stop" in actions(ui)) is stop


def test_the_service_is_stopped_and_can_be_started_again(ui: Ui, systemctl: FakeSystemctl, dialogs: FakeDialogs):
    def stop(command: list[str]) -> str:
        if command[2] == "stop":
            systemctl.properties = STOPPED
        return systemctl(command)

    ui.app.shell.service._run = stop
    do(ui, "Stop")

    assert ["systemctl", "--user", "stop", "--no-block", UNIT_NAME] in systemctl.commands
    # stopped, not disabled: it starts again with the next session
    assert ["systemctl", "--user", "disable", UNIT_NAME] not in systemctl.commands
    assert status(ui) == "Stopping the service…"
    assert dialogs.shown == []
    assert (ui.text("service_pill"), ui.text("service_button")) == ("stopped", "Start")
    assert actions(ui) == ["Start"]


def test_a_failing_stop_is_reported(ui: Ui, dialogs: FakeDialogs):
    def fail(command: list[str]) -> str:
        raise ServiceError("systemctl --user stop failed: nope")

    ui.app.shell.service._run = fail
    do(ui, "Stop")

    assert dialogs.shown == ["systemctl --user stop failed: nope"]
    assert status(ui) == ""
    assert actions(ui) == []


def test_a_daemon_elsewhere_can_not_be_stopped_here(make_ui: MakeUi, path: Path):
    ui = make_ui(find_daemon=lambda: RecordingInstance(4242, path.resolve(), systemd=False))

    assert actions(ui) == []


def test_the_popover_of_the_pill_opens_with_a_click_and_lists_the_service(ui: Ui):
    ui.click("service_pill")

    assert popup(ui, "service_details").property("opened") is True
    assert popup(ui, "service_details").property("title") == "Service"
    assert ui.shows("details_row_0")
    assert ui.shows("details_action_0_1")  # Restart, Stop


def test_the_header_shows_which_unit_runs_the_service(make_ui: MakeUi, systemctl: FakeSystemctl):
    systemctl.properties = unit_properties(
        RUNNING, Path("/home/me/.config/systemd/user/xtouch-daemon.service"), CHECKOUT
    )
    ui = make_ui()

    unit = details(ui, "Unit")
    assert unit is not None
    assert unit.status == Status("own unit", Tone.NEUTRAL, f"Your own unit, which starts `{CHECKOUT}`.")
    assert unit.path == "/home/me/.config/systemd/user/xtouch-daemon.service"
    # without a package there is nothing it overrides
    assert actions(ui, "Unit") == []

    systemctl.properties = unit_properties(RUNNING, systemd.PACKAGED_UNIT, "/usr/bin/xtouch-daemon")
    ui.app.shell.refresh_service()
    unit = details(ui, "Unit")
    assert unit is not None
    assert unit.status is not None
    assert unit.status.text == "packaged"

    systemctl.properties = MISSING
    ui.app.shell.refresh_service()
    assert details(ui, "Unit") is None


@pytest.mark.parametrize("answer", [YES, "no"])
def test_the_unit_that_overrides_the_package_can_be_removed(
    make_ui: MakeUi, systemctl: FakeSystemctl, dialogs: FakeDialogs, answer: str
):
    install_package()
    write_user_unit()
    systemctl.properties = unit_properties(RUNNING, unit_path(), CHECKOUT)
    ui = make_ui()
    unit = details(ui, "Unit")
    assert unit is not None
    assert unit.status is not None
    assert unit.status.tip.endswith("It overrides the unit of the package.")
    dialogs.answer = answer

    do(ui, "Use the packaged unit", "Unit")

    assert dialogs.shown[0].startswith(f"Remove {unit_path()}?")
    if answer == "no":
        assert unit_path().exists()
        assert ["systemctl", "--user", "disable", UNIT_NAME] not in systemctl.commands
        return
    assert not unit_path().exists()
    assert ["systemctl", "--user", "restart", "--no-block", UNIT_NAME] in systemctl.commands
    assert status(ui) == f"Removed {unit_path()}: the service uses the unit of the package."
    assert actions(ui, "Unit") == []


def test_a_failing_removal_of_the_override_is_reported(make_ui: MakeUi, systemctl: FakeSystemctl, dialogs: FakeDialogs):
    install_package()
    write_user_unit()
    systemctl.properties = unit_properties(RUNNING, unit_path(), CHECKOUT)
    ui = make_ui()

    def fail(command: list[str]) -> str:
        if command[2] == "show":
            return RUNNING
        raise ServiceError("systemctl --user disable failed: nope")

    ui.app.shell.service._run = fail
    dialogs.answer = YES
    do(ui, "Use the packaged unit", "Unit")

    assert dialogs.shown[1:] == ["systemctl --user disable failed: nope"]
    assert status(ui) == ""


def test_the_package_starts_its_own_unit(make_ui: MakeUi, systemctl: FakeSystemctl, dialogs: FakeDialogs):
    install_package()
    systemctl.properties = MISSING
    ui = make_ui()
    assert ui.item("service_button").property("tip") == "Enable the unit of the package and start it"
    dialogs.answer = YES

    ui.click("service_button")

    assert dialogs.shown == [
        f"Enable {UNIT_NAME} of the package (it starts with the session from now on) and start it?"
    ]
    assert not unit_path().exists()
    assert ["systemctl", "--user", "enable", "--now", "--no-block", UNIT_NAME] in systemctl.commands
    assert status(ui) == "Enabled the unit of the package; starting the service…"


def test_restart_stands_out_when_the_daemon_runs_an_older_version(
    make_ui: MakeUi,
    systemctl: FakeSystemctl,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setattr(service_module, "executable", lambda: "/usr/bin/xtouch-daemon")
    monkeypatch.setattr(service_module, "installed_version", lambda: "0.2.0")
    systemctl.properties = unit_properties(RUNNING, systemd.PACKAGED_UNIT, "/usr/bin/xtouch-daemon")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="xtg-") as directory:
        live = FakeLiveDaemon(Path(directory) / "live.sock")
        ui = make_ui(live_socket=live.path)
        try:
            ui.wait_until(lambda: bool(live.clients))
            current = dataclasses.replace(_snapshot(ui, live), daemon_version="0.2.0")
            live.send(current)
            ui.wait_until(lambda: ui.app.shell.live.snapshot is not None)
            ui.app.shell.refresh_service()
            assert not ui.shows("service_button")

            # after an upgrade of the package
            live.send(dataclasses.replace(current, daemon_version="0.1.0"))
            ui.wait_until(
                lambda: ui.app.shell.live.snapshot is not None and ui.app.shell.live.snapshot.daemon_version == "0.1.0"
            )
            ui.app.shell.refresh_service()

            assert ui.text("service_button") == "Restart"
            assert ui.shows("service_button")
            assert ui.item("service_button").property("highlighted") is True
            assert ui.item("service_button").property("tip") == (
                "The daemon runs version 0.1.0, 0.2.0 is installed: restart it to run 0.2.0"
            )
        finally:
            ui.app.shell.live.disconnect_from_daemon()
            live.close()


def _snapshot(ui: Ui, live: FakeLiveDaemon):
    saved = ui.app.shell.document.saved_config
    assert saved is not None
    from xtouch_daemon.live.messages import Snapshot, fingerprint

    strips = tuple(strip_state() for _ in range(8))
    return Snapshot(fingerprint(saved), True, sound_server=True, mqtt=None, strips=strips)


def test_a_failing_systemctl_is_reported(ui: Ui, dialogs: FakeDialogs):
    def fail(command: list[str]) -> str:
        raise ServiceError("systemctl --user restart failed: nope")

    ui.app.shell.service._run = fail
    do(ui, "Restart")
    assert dialogs.shown == ["systemctl --user restart failed: nope"]
    assert ui.text("service_pill") == "unavailable"
    assert not ui.shows("service_button")


def test_a_changed_device_needs_no_restart(ui: Ui, daemon: RecordingInstance):
    ui.app.editor.document.set(("device", "name"), "Other")
    ui.app.editor.edited()

    assert ui.app.shell.save()
    # the daemon switches to that device when it reloads
    assert daemon.reloads == [1234]
    assert not ui.shows("restart_button")


def test_a_changed_mqtt_section_offers_a_restart_instead_of_a_reload(
    ui: Ui, daemon: RecordingInstance, systemctl: FakeSystemctl
):
    ui.app.editor.document.add_section("mqtt")
    ui.app.editor.document.set(("mqtt", "host"), "broker")
    ui.app.editor.edited()

    assert ui.app.shell.save()
    ui.settle()

    assert daemon.reloads == []
    assert status(ui) == "Saved. The [mqtt] section changed: restart the service to use the configuration."
    assert ui.shows("restart_button")

    ui.click("restart_button")
    assert systemctl.commands[-2] == ["systemctl", "--user", "restart", "--no-block", UNIT_NAME]
    assert status(ui) == "Restarting the service…"
    assert not ui.shows("restart_button")


def test_a_failing_restart_or_reload_is_reported(ui: Ui, dialogs: FakeDialogs):
    ui.app.editor.document.add_section("mqtt")
    ui.app.editor.document.set(("mqtt", "host"), "broker")
    ui.app.editor.edited()
    ui.app.shell.save()
    ui.settle()

    def fail(command: list[str]) -> str:
        if command[2] == "show":
            return RUNNING
        raise ServiceError(f"{command[2]} failed")

    ui.app.shell.service._run = fail
    ui.click("restart_button")
    assert dialogs.shown == ["restart failed"]

    # it ended a moment ago
    shell = ui.app.shell
    shell.find_daemon = lambda: RecordingInstance(1234, shell.document.path.resolve(), systemd=True, gone=True)
    shell.refresh_service()
    shell.document.set(("device", "name"), "Third")
    ui.app.editor.edited()
    assert shell.save()
    assert status(ui) == "Saved, but reloading the service failed: [Errno 3] No such process"


def test_a_daemon_started_elsewhere_is_shown_and_reloaded(make_ui: MakeUi, path: Path):
    daemon = RecordingInstance(4242, path.resolve(), systemd=False)
    ui = make_ui(find_daemon=lambda: daemon)

    assert (ui.text("service_pill"), ui.item("service_pill").property("tone")) == ("running elsewhere", "good")
    assert "process 4242" in ui.item("service_pill").property("tip")
    assert not ui.shows("service_button")
    assert [entry.title for entry in entries(ui)] == ["Service"]
    assert actions(ui) == []

    ui.app.editor.document.set(("device", "name"), "Other")
    ui.app.editor.edited()
    assert ui.app.shell.save()

    assert daemon.reloads == [4242]
    assert status(ui) == "Saved and reloaded: the device shows the new configuration."
    # the window restarts only the service
    assert not ui.shows("restart_button")


def test_without_a_daemon_saving_only_saves(make_ui: MakeUi, systemctl: FakeSystemctl):
    systemctl.properties = STOPPED
    ui = make_ui(find_daemon=lambda: None)
    ui.app.editor.document.set(("device", "name"), "Other")
    ui.app.editor.edited()

    assert ui.app.shell.save()

    assert status(ui) == "Saved. The daemon is not running: the button next to the service (top right) starts it."
    assert not ui.shows("restart_button")


def test_saving_what_did_not_change_does_nothing(ui: Ui, path: Path):
    before = path.stat().st_mtime_ns
    assert ui.app.shell.save()
    assert path.stat().st_mtime_ns == before


def test_invalid_changes_are_not_saved(ui: Ui, dialogs: FakeDialogs, path: Path):
    ui.app.editor.document.set(("behavior", "max_volume"), "loud")
    ui.app.editor.edited()
    assert ui.app.shell.problems

    assert not ui.app.shell.save()

    assert dialogs.titles == ["Not saved"]
    assert "loud" not in path.read_text()


def test_a_file_that_can_not_be_written_is_reported(ui: Ui, path: Path, dialogs: FakeDialogs):
    ui.app.editor.document.set(("behavior", "max_volume"), 110)
    ui.app.editor.edited()
    path.chmod(0o400)
    try:
        assert not ui.app.shell.save()
    finally:
        path.chmod(0o600)
    assert dialogs.titles == ["Saving failed"]
    assert dialogs.shown[0].startswith("[Errno 13] Permission denied")


def test_a_new_file_can_be_saved_right_away(make_ui: MakeUi, tmp_path: Path):
    ui = make_ui(file=tmp_path / "new.toml")

    assert ui.window.title() == "new.toml (new)"
    assert ui.item("save_button").isEnabled()
    assert ui.app.shell.save()
    assert tomllib.loads((tmp_path / "new.toml").read_text()) == {}
    assert status(ui).startswith("Saved. The service reads")


def test_save_and_revert_follow_the_changes(ui: Ui):
    assert not ui.item("save_button").isEnabled()
    assert not ui.item("revert_button").isEnabled()
    assert not ui.item("undo_button").isEnabled()

    ui.app.editor.document.set(("behavior", "max_volume"), 110)
    ui.app.editor.edited()
    ui.settle()

    assert ui.window.title() == "• config.toml"
    assert ui.item("save_button").isEnabled()
    assert ui.item("revert_button").isEnabled()
    assert ui.item("undo_button").isEnabled()
    assert not ui.item("redo_button").isEnabled()


def test_revert_drops_the_changes(ui: Ui):
    ui.app.editor.document.unset(("channel", "browser"))
    ui.app.editor.edited()
    ui.settle()

    ui.click("revert_button")

    assert ui.app.editor.document.get(("channel", "browser", "label")) == "Browser"
    assert status(ui) == "Reverted to the file. Ctrl+Z brings the changes back."


def test_undo_and_redo_say_so(ui: Ui):
    ui.app.editor.document.set(("behavior", "max_volume"), 110)
    ui.app.editor.edited()
    ui.settle()

    ui.click("undo_button")
    assert (status(ui), ui.app.editor.document.get(("behavior", "max_volume"))) == ("Undone.", 120)
    ui.click("redo_button")
    assert (status(ui), ui.app.editor.document.get(("behavior", "max_volume"))) == ("Redone.", 110)


@pytest.mark.parametrize(
    ("answer", "closed", "saved"),
    [(DISCARD, True, False), (SAVE, True, True), (CANCEL, False, False)],
)
def test_closing_asks_about_unsaved_changes(
    ui: Ui, path: Path, dialogs: FakeDialogs, answer: str, closed: bool, saved: bool
):
    ui.app.editor.document.set(("behavior", "max_volume"), 110)
    ui.app.editor.edited()
    dialogs.answer = answer

    ui.window.close()
    ui.settle()

    assert ui.window.isVisible() is not closed
    assert dialogs.shown == ["Save the changes before closing?"]
    assert ("max_volume = 110" in path.read_text()) == saved
    dialogs.answer = DISCARD


def test_closing_without_changes_does_not_ask(ui: Ui, dialogs: FakeDialogs):
    ui.window.close()
    ui.settle()

    assert not ui.window.isVisible()
    assert dialogs.shown == []


def test_quit_in_the_menu_closes_the_window(ui: Ui):
    ui.app.shell.trigger("quit")
    ui.settle()

    assert not ui.window.isVisible()
