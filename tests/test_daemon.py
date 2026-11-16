import asyncio
import logging
import os
import signal
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from tests.conftest import FakeBackend, RecordingSurface, finish_tasks, output, settle
from tests.fake_mqtt import FakeBroker
from xtouch_daemon import __version__, live, protocol
from xtouch_daemon import daemon as daemon_module
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon import surface as surface_module
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config import Config, parse_config
from xtouch_daemon.daemon import Daemon
from xtouch_daemon.live import EndPreview, KeepPreview, Reply, StartPreview
from xtouch_daemon.media import MediaPlayers
from xtouch_daemon.mixer import Mixer
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.protocol import Button, Color, Led
from xtouch_daemon.surface import Surface

SPEAKER = '[[strip]]\ntype = "output"\ndevice = "speaker"\nlabel = "Speaker"\ncolor = "cyan"\n'
STATE = AudioState(outputs=(output("speaker", 50),), default_output="speaker")


class Notifications(list[tuple[str, ...]]):
    def states(self) -> list[str]:
        return [state for notification in self for state in notification]


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> Notifications:
    sent = Notifications()

    def notify(*states: str) -> bool:
        sent.append(states)
        return True

    monkeypatch.setattr(daemon_module.systemd, "notify", notify)
    monkeypatch.setattr(daemon_module.systemd, "reloading", lambda: notify("RELOADING=1"))
    return sent


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(SPEAKER)
    return path


def quiet_mixer(
    surface: Surface,
    backend: AudioBackend,
    config: Config,
    *,
    bridge: MqttBridge | None,
    players: MediaPlayers | None = None,
    preview: bool = False,
) -> Mixer:
    # meters that capture nothing: the tests don't touch the audio of the machine they run on
    return Mixer(surface, backend, config, capture_command="true", bridge=bridge, players=players, preview=preview)


def make(config_path: Path, surface: RecordingSurface, backend: FakeBackend) -> Daemon:
    return Daemon(parse_config(config_path.read_text()), backend, surface, config_path, mixer_factory=quiet_mixer)


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


async def until(condition: object) -> None:
    for _ in range(100):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the condition never became true")


async def test_the_daemon_runs_until_it_is_stopped_and_leaves_the_surface_dark(
    config_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    daemon = make(config_path, surface, FakeBackend((STATE,)))

    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Speaker", "50%"])
    assert ("READY=1", "STATUS=waiting for X-Touch-Ext, waiting for the sound server") in notifications
    assert ("STATUS=waiting for X-Touch-Ext, sound server connected",) in notifications

    daemon.stop()
    await task

    assert notifications[-1] == ("STOPPING=1",)
    assert surface.strips[0].color == Color.BLACK
    assert surface.strips[0].text == ["", ""]
    assert daemon.mixer.meters[0].targets == set()


async def test_sigterm_stops_the_daemon(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, notifications: Notifications
) -> None:
    daemon = make(config_path, surface, backend)
    task = asyncio.create_task(daemon.run())
    await until(lambda: notifications)

    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, 1)

    assert "STOPPING=1" in notifications.states()


async def test_more_signals_while_stopping_do_not_cut_the_shutdown_short(
    config_path: Path,
    surface: RecordingSurface,
    notifications: Notifications,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    daemon = make(config_path, surface, FakeBackend((STATE,)))
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Speaker", "50%"])
    await surface.settled()
    # the faders take a while to go down: signals come in meanwhile
    monkeypatch.setattr(surface_module, "FADER_SLOW_SMOOTH_TIME", 0.3)

    os.kill(os.getpid(), signal.SIGINT)
    await until(lambda: "STOPPING=1" in notifications.states())
    os.kill(os.getpid(), signal.SIGINT)
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, 5)

    assert "Stopping already" in caplog.text
    assert surface.faders(0)[-1] == 0
    assert surface.strips[0].text == ["", ""]


async def test_sighup_loads_the_configuration_again(
    config_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    daemon = make(config_path, surface, FakeBackend((STATE,)))
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text[0] == "Speaker")

    config_path.write_text(SPEAKER.replace('"Speaker"', '"Boxes"'))
    os.kill(os.getpid(), signal.SIGHUP)
    await until(lambda: surface.strips[0].text[0] == "Boxes")
    daemon.stop()
    await task

    states = notifications.states()
    assert states.index("RELOADING=1") < len(states) - states[::-1].index("READY=1") - 1


async def test_a_reload_builds_new_strips_with_the_current_state(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, notifications: Notifications
) -> None:
    daemon = make(config_path, surface, backend)
    daemon.mixer.on_state(STATE)
    old = daemon.mixer

    config_path.write_text(SPEAKER.replace("cyan", "green"))
    assert daemon.reload()

    assert daemon.mixer is not old
    assert surface.strips[0].color == Color.GREEN
    assert surface.strips[0].text == ["Speaker", "50%"]
    assert notifications[-1][0] == "READY=1"
    daemon.mixer.close()
    daemon.stop()
    await settle()


async def test_a_configuration_with_errors_is_reported_and_the_current_one_kept(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    caplog: pytest.LogCaptureFixture,
) -> None:
    daemon = make(config_path, surface, backend)
    old = daemon.mixer

    config_path.write_text('[[strip]]\ntype = "loud"\n')
    assert not daemon.reload()

    assert daemon.mixer is old
    assert "Keeping the current configuration" in caplog.text
    assert notifications[-1] == ("READY=1", "STATUS=Configuration has errors, see the log")


async def test_a_changed_device_name_needs_a_restart(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path.write_text("[device]\ntouchless_faders = [1, 8]\n" + SPEAKER)
    daemon = make(config_path, surface, backend)
    assert surface.touchless == {0, 7}

    # the faders without a touch sensor change with a reload
    config_path.write_text("[device]\ntouchless_faders = [2]\n" + SPEAKER)
    assert daemon.reload()
    assert surface.touchless == {1}
    # every fader, without the need of a touch
    config_path.write_text("[device]\ntouch_required = false\ntouchless_faders = [2]\n" + SPEAKER)
    assert daemon.reload()
    assert surface.touchless == set(range(8))
    # the sequences too
    config_path.write_text('[device]\nstartup = "show"\nshutdown = "curtain"\n' + SPEAKER)
    assert daemon.reload()
    assert (surface.startup, surface.shutdown) == ("show", "curtain")
    assert "restart the daemon" not in caplog.text

    config_path.write_text('[device]\nname = "X-Touch"\n' + SPEAKER)
    assert daemon.reload()

    assert "The name in the [device] section changed: restart the daemon" in caplog.text
    assert surface.touchless == frozenset()
    assert (surface.startup, surface.shutdown) == ("sweep", "sweep")
    daemon.mixer.close()
    await settle()


async def test_a_part_that_ends_ends_the_daemon_with_its_error(
    config_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    class BrokenBackend(FakeBackend):
        async def run(self, on_state: object) -> None:
            raise RuntimeError("broken")

    daemon = make(config_path, surface, BrokenBackend())

    with pytest.raises(RuntimeError, match="broken"):
        await daemon.run()

    assert notifications[-1] == ("STOPPING=1",)


async def test_the_status_follows_the_connections(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, notifications: Notifications
) -> None:
    daemon = make(config_path, surface, backend)

    daemon._on_state(STATE)
    daemon._on_state(STATE)  # nothing changed: no notification
    daemon._on_state(DISCONNECTED)
    surface.on_connection(True)

    assert notifications == [
        ("STATUS=waiting for X-Touch-Ext, sound server connected",),
        ("STATUS=waiting for X-Touch-Ext, waiting for the sound server",),
        ("STATUS=waiting for X-Touch-Ext, waiting for the sound server",),
    ]


async def test_events_of_the_surface_go_to_the_current_mixer(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, notifications: Notifications
) -> None:
    from xtouch_daemon.protocol import Button, ButtonPressed

    daemon = make(config_path, surface, backend)
    daemon.reload()
    daemon.mixer.on_state(STATE)

    surface.on_event(ButtonPressed(0, Button.MUTE, True))
    await settle()

    assert backend.calls[-1][0] == "set_device_mute"
    daemon.mixer.close()


async def test_a_daemon_without_surface_makes_one_for_the_configured_device(backend: FakeBackend) -> None:
    daemon = Daemon(parse_config('[device]\nname = "X-Touch"\n'), backend)

    assert daemon.surface.device_name == "X-Touch"
    logging.getLogger().debug("no tasks were started")


# -- Home Assistant ---------------------------------------------------------------------------------------------------

HOME_ASSISTANT = '[[strip]]\ntype = "homeassistant"\nlabel = "Lights"\n\n[mqtt]\nhost = "broker"\n'


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> FakeBroker:
    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    return FakeBroker()


def make_with_mqtt(config_path: Path, surface: RecordingSurface, backend: FakeBackend, broker: FakeBroker) -> Daemon:
    config = parse_config(config_path.read_text())
    assert config.mqtt is not None
    bridge = MqttBridge(config.mqtt, client_factory=broker.client)
    return Daemon(config, backend, surface, config_path, mixer_factory=quiet_mixer, bridge=bridge)


async def test_home_assistant_strips_follow_the_broker(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    broker: FakeBroker,
    notifications: Notifications,
) -> None:
    config_path.write_text(HOME_ASSISTANT)
    daemon = make_with_mqtt(config_path, surface, backend, broker)
    assert daemon.bridge is not None

    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Lights", ""])
    assert "STATUS=waiting for X-Touch-Ext, waiting for the sound server, MQTT connected" in notifications.states()

    # the device comes and goes: Home Assistant shows the entities as available or not
    surface.on_connection(True)
    await until(lambda: broker.retained.get("xtouch-daemon/xtouch/availability") == "online")
    surface.on_connection(False)
    await until(lambda: broker.retained.get("xtouch-daemon/xtouch/availability") == "offline")
    surface.on_connection(True)
    await until(lambda: broker.retained.get("xtouch-daemon/xtouch/availability") == "online")

    daemon.stop()
    await task

    # stopping marks them unavailable right away
    assert broker.retained["xtouch-daemon/xtouch/availability"] == "offline"


async def test_the_live_view_shows_what_the_daemon_does(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, broker: FakeBroker
) -> None:
    config_path.write_text(HOME_ASSISTANT)
    config = parse_config(HOME_ASSISTANT)
    assert config.mqtt is not None
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        socket = Path(directory) / "live.sock"
        daemon = Daemon(
            config,
            backend,
            surface,
            config_path,
            mixer_factory=quiet_mixer,
            bridge=MqttBridge(config.mqtt, client_factory=broker.client),
            live_socket=socket,
        )
        task = asyncio.create_task(daemon.run())
        await until(lambda: surface.strips[0].text == ["Lights", ""] and daemon.bridge and daemon.bridge.connected)
        await until(socket.exists)

        reader, writer = await asyncio.open_unix_connection(socket)
        snapshot = live.decode(await reader.readline())
        assert snapshot is not None
        assert snapshot.config == live.fingerprint(config)
        assert (snapshot.device, snapshot.sound_server, snapshot.mqtt) == (False, False, True)
        state = snapshot.mqtt_state
        assert state is not None
        assert (state.broker, state.username, state.connected, state.error, state.entities) == (
            "broker:1883",
            None,
            True,
            None,
            11,
        )
        assert snapshot.strips[0].text == ("Lights", "")

        daemon.stop()
        await task
        # it is gone with the daemon
        assert not socket.exists()
        writer.close()


async def test_without_mqtt_section_there_is_no_bridge(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend
) -> None:
    daemon = make(config_path, surface, backend)
    assert daemon.bridge is None
    assert daemon.snapshot().mqtt is None
    # the GUI tells whether it runs the installed version
    assert daemon.snapshot().daemon_version == __version__
    config = parse_config(HOME_ASSISTANT)
    assert Daemon(config, backend, surface, mixer_factory=quiet_mixer).bridge is not None


async def test_a_changed_mqtt_section_needs_a_restart(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    broker: FakeBroker,
    notifications: Notifications,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path.write_text(HOME_ASSISTANT)
    daemon = make_with_mqtt(config_path, surface, backend, broker)
    old = daemon.mixer

    config_path.write_text(HOME_ASSISTANT.replace('"broker"', '"other"'))
    assert not daemon.reload()

    assert daemon.mixer is old
    assert "the [mqtt] section changed" in caplog.text
    assert notifications[-1] == ("READY=1", "STATUS=The [mqtt] section changed, restart the daemon")


async def test_a_reload_gives_the_bridge_the_new_strips(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, broker: FakeBroker, notifications: Notifications
) -> None:
    config_path.write_text(HOME_ASSISTANT)
    daemon = make_with_mqtt(config_path, surface, backend, broker)
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Lights", ""])

    config_path.write_text(HOME_ASSISTANT.replace('"homeassistant"', '"homeassistant"\nid = "desk"'))
    assert daemon.reload()
    await until(lambda: "homeassistant/number/xtouch/desk_fader/config" in broker.retained)
    daemon.stop()
    await task

    assert "homeassistant/number/xtouch/strip_1_fader/config" not in broker.retained


# -- stopping -------------------------------------------------------------------------------------------------------


class StreamingBackend(FakeBackend):
    """A sound server that keeps reporting, as one does while something plays."""

    async def run(self, on_state: Callable[[AudioState], None]) -> None:
        while True:
            on_state(STATE)
            await asyncio.sleep(0.001)


async def test_nothing_shows_on_the_surface_after_it_was_turned_dark(
    config_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    daemon = make(config_path, surface, StreamingBackend())
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Speaker", "50%"])
    await surface.settled()

    daemon.stop()
    # a hand on the device while it stops changes nothing
    surface.on_event(protocol.ButtonPressed(0, Button.MUTE, True))
    await task

    dark = protocol.lcd_text(0, 0, "")
    after = surface.sent[surface.sent.index(dark) :]
    blank_texts = {protocol.lcd_text(strip, line, "") for strip in range(protocol.STRIPS) for line in (0, 1)}
    for message in after:
        if message.startswith(protocol.SYSEX_HEADER + b"\x12"):
            assert message in blank_texts
        if message.startswith(protocol.SYSEX_HEADER + b"\x72"):
            assert message == protocol.lcd_colors([Color.BLACK] * protocol.STRIPS)
    # after the dark point the faders only go down
    faders = [m[1] | m[2] << 7 for m in after if m[0] == 0xE0]
    assert faders == sorted(faders, reverse=True)
    for strip in surface.strips:
        assert strip.color == Color.BLACK
        assert strip.text == ["", ""]
        assert all(led == Led.OFF for led in strip.leds.values())
    assert surface.faders(0)[-1] == 0


async def test_the_media_players_follow_while_the_daemon_runs_and_go_to_every_mixer(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend
) -> None:
    class Players:
        players = ()
        running = asyncio.Event()

        async def run(self) -> None:
            self.running.set()
            await asyncio.Event().wait()

    players = Players()
    daemon = Daemon(
        parse_config(config_path.read_text()),
        backend,
        surface,
        config_path,
        mixer_factory=quiet_mixer,
        players=players,  # type: ignore[arg-type]
    )
    assert daemon.mixer.controllers[0].env.players is players
    task = asyncio.create_task(daemon.run())
    await asyncio.wait_for(players.running.wait(), 1)
    assert daemon.reload()
    assert daemon.mixer.controllers[0].env.players is players
    daemon.stop()
    await task


# -- the live preview of the GUI ------------------------------------------------------------------------------------

BOXES = SPEAKER.replace('"Speaker"', '"Boxes"')


class Told(list[tuple[object, Reply]]):
    """What the daemon told the clients of the live view without being asked."""

    def reasons(self, client: object) -> list[str]:
        return [reply.message for to, reply in self if to is client and reply.kind == "ended"]


def make_previewing(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> tuple[Daemon, Told]:
    """A daemon with a live view (not served: the tests hand it the requests) that records what it tells."""
    daemon = Daemon(
        parse_config(config_path.read_text()),
        backend,
        surface,
        config_path,
        mixer_factory=quiet_mixer,
        live_socket=config_path.with_name("live.sock"),
    )
    told = Told()
    assert daemon.live is not None
    monkeypatch.setattr(daemon.live, "tell", lambda client, reply: told.append((client, reply)))
    daemon.mixer.on_state(STATE)
    return daemon, told


async def test_a_preview_runs_the_configuration_of_the_gui_and_never_writes_the_file(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    daemon, told = make_previewing(config_path, surface, backend, monkeypatch)
    gui, other = object(), object()
    assert daemon.snapshot().features == live.FEATURES
    assert not daemon.snapshot().preview

    assert daemon.on_request(gui, StartPreview(BOXES)) == Reply("preview", True)

    assert surface.strips[0].text == ["Boxes", "50%"]
    assert config_path.read_text() == SPEAKER
    assert daemon.previewing
    assert daemon.mixer.preview
    snapshot = daemon.snapshot()
    assert snapshot.preview
    assert snapshot.config == live.fingerprint(parse_config(BOXES))
    assert notifications[-1] == (
        "STATUS=waiting for X-Touch-Ext, sound server connected, previewing unsaved changes of the GUI",
    )
    assert "Previewing a configuration of the GUI, the file stays as it is" in caplog.text

    # the same again changes nothing, another one follows
    mixer = daemon.mixer
    assert daemon.on_request(gui, StartPreview(BOXES)) == Reply("preview", True)
    assert daemon.mixer is mixer
    assert daemon.on_request(gui, StartPreview(BOXES.replace("cyan", "green"))) == Reply("preview", True)
    assert surface.strips[0].color == Color.GREEN

    # one with errors is not used: the GUI learns why
    reply = daemon.on_request(gui, StartPreview('[[strip]]\ntype = "loud"\n'))
    assert reply is not None
    assert not reply.ok
    assert reply.message.startswith("The previewed configuration has errors:\n  strip[1]")
    assert surface.strips[0].color == Color.GREEN
    reply = daemon.on_request(gui, StartPreview("[[strip"))
    assert reply is not None
    assert "is not valid TOML" in reply.message
    # Home Assistant needs a restart for another broker
    reply = daemon.on_request(gui, StartPreview(BOXES + '[mqtt]\nhost = "broker"\n'))
    assert reply == Reply(
        "preview",
        False,
        "A preview can't change the [mqtt] section: save it and restart the daemon, or undo the change.",
    )
    # and so does the device name, which the reply says
    assert daemon.on_request(gui, StartPreview('[device]\nname = "X-Touch"\n' + BOXES)) == Reply(
        "preview", True, "The device name changes only with a restart."
    )

    # only the GUI that previews ends it
    assert daemon.on_request(other, KeepPreview()) is None
    assert daemon.on_request(other, EndPreview()) is None
    daemon.on_client_closed(other)
    assert daemon.previewing
    assert daemon.on_request(gui, KeepPreview()) is None
    assert daemon.on_request(gui, EndPreview()) is None

    assert surface.strips[0].text == ["Speaker", "50%"]
    assert surface.strips[0].color == Color.CYAN
    assert not daemon.previewing
    assert not daemon.mixer.preview
    assert told.reasons(gui) == ["the GUI ended it"]
    assert notifications[-1] == ("STATUS=waiting for X-Touch-Ext, sound server connected",)
    assert "The preview ended, the GUI ended it" in caplog.text
    # nothing to end anymore
    assert daemon.on_request(gui, EndPreview()) is None
    assert told.reasons(gui) == ["the GUI ended it"]
    daemon.mixer.close()
    await settle()


async def test_another_window_takes_the_preview_over_and_the_file_returns_when_it_goes(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon, told = make_previewing(config_path, surface, backend, monkeypatch)
    first, second = object(), object()
    daemon.on_request(first, StartPreview(BOXES))

    daemon.on_request(second, StartPreview(SPEAKER.replace('"Speaker"', '"Desk"')))

    assert surface.strips[0].text == ["Desk", "50%"]
    assert told.reasons(first) == ["another window previews now"]
    # the first one going away does nothing now
    daemon.on_client_closed(first)
    assert daemon.previewing
    # the second one crashed: its connection ended
    daemon.on_client_closed(second)
    assert surface.strips[0].text == ["Speaker", "50%"]
    assert told.reasons(second) == ["the GUI went away"]
    daemon.mixer.close()
    await settle()


async def test_a_preview_ends_without_a_heartbeat_and_when_the_file_changes(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daemon_module, "PREVIEW_CHECK", 0.01)
    monkeypatch.setattr(daemon_module, "PREVIEW_TIMEOUT", 0.2)
    daemon, told = make_previewing(config_path, surface, backend, monkeypatch)
    gui = object()

    daemon.on_request(gui, StartPreview(BOXES))
    # a heartbeat keeps it going
    for _ in range(3):
        await asyncio.sleep(0.1)
        daemon.on_request(gui, KeepPreview())
    assert daemon.previewing
    await until(lambda: not daemon.previewing)
    assert surface.strips[0].text == ["Speaker", "50%"]
    assert told.reasons(gui) == ["no word from the GUI for 0 s"]

    # the file changed meanwhile (e.g. in a text editor): it runs
    monkeypatch.setattr(daemon_module, "PREVIEW_TIMEOUT", 10.0)
    daemon.on_request(gui, StartPreview(BOXES))
    config_path.write_text(SPEAKER.replace('"Speaker"', '"Desk"'))
    await until(lambda: not daemon.previewing)
    assert surface.strips[0].text == ["Desk", "50%"]
    assert told.reasons(gui)[-1] == "the configuration file was loaded"
    assert daemon.file_config == parse_config(SPEAKER.replace('"Speaker"', '"Desk"'))
    daemon.mixer.close()
    await settle()


async def test_a_reload_ends_the_preview_also_when_the_file_can_not_be_used(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon, told = make_previewing(config_path, surface, backend, monkeypatch)
    gui = object()
    daemon.on_request(gui, StartPreview(BOXES))

    # saved by the GUI, which then reloads: the preview is the configuration now
    config_path.write_text(BOXES.replace("cyan", "green"))
    assert daemon.reload()
    assert not daemon.previewing
    assert surface.strips[0].color == Color.GREEN
    assert told.reasons(gui) == ["the configuration file was loaded"]

    # a file with errors: the one before runs, not the preview
    daemon.on_request(gui, StartPreview(SPEAKER.replace('"Speaker"', '"Desk"')))
    config_path.write_text('[[strip]]\ntype = "loud"\n')
    assert not daemon.reload()
    assert not daemon.previewing
    assert surface.strips[0].text == ["Boxes", "50%"]
    assert told.reasons(gui)[-1] == "the configuration file has errors, the device runs the one before"
    # without a file at all
    daemon.on_request(gui, StartPreview(SPEAKER))
    config_path.unlink()
    assert not daemon.reload()
    assert surface.strips[0].text == ["Boxes", "50%"]
    daemon.mixer.close()
    await settle()


async def test_a_reload_with_another_broker_ends_the_preview(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    broker: FakeBroker,
    notifications: Notifications,
) -> None:
    config_path.write_text(HOME_ASSISTANT)
    daemon = make_with_mqtt(config_path, surface, backend, broker)
    gui = object()
    assert daemon.on_request(gui, StartPreview(HOME_ASSISTANT.replace("Lights", "Desk"))) == Reply("preview", True)
    assert daemon.config == parse_config(HOME_ASSISTANT.replace("Lights", "Desk"))

    config_path.write_text(HOME_ASSISTANT.replace('"broker"', '"other"'))
    assert not daemon.reload()

    assert not daemon.previewing
    assert daemon.config == parse_config(HOME_ASSISTANT)
    daemon.mixer.close()
    await settle()


async def test_the_gui_previews_through_the_live_view_while_the_daemon_runs(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    broker: FakeBroker,
    notifications: Notifications,
) -> None:
    config_path.write_text(HOME_ASSISTANT)
    config = parse_config(HOME_ASSISTANT)
    assert config.mqtt is not None
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        socket = Path(directory) / "live.sock"
        daemon = Daemon(
            config,
            backend,
            surface,
            config_path,
            mixer_factory=quiet_mixer,
            bridge=MqttBridge(config.mqtt, client_factory=broker.client),
            live_socket=socket,
        )
        task = asyncio.create_task(daemon.run())
        await until(lambda: daemon.bridge is not None and daemon.bridge.ready and socket.exists())
        lights = "homeassistant/number/xtouch/strip_1_fader/config"
        assert lights in broker.retained

        reader, writer = await asyncio.open_unix_connection(socket)
        # a preview without the Home Assistant strip: its entities stay in Home Assistant
        writer.write(live.encode_request(StartPreview(SPEAKER + '[mqtt]\nhost = "broker"\n')))
        while not isinstance(reply := live.decode_message(await reader.readline()), Reply):
            pass
        assert reply == Reply("preview", True)
        await until(lambda: surface.strips[0].text[0] == "Speaker")
        snapshot = None
        while snapshot is None or not snapshot.preview:
            snapshot = live.decode(await reader.readline())
        await until(lambda: daemon.bridge is not None and daemon.bridge.ready)
        assert lights in broker.retained
        assert daemon.bridge is not None
        assert daemon.bridge.entity_count == 0

        # the GUI closed: back to the file, with the entities as they were
        writer.close()
        await until(lambda: not daemon.previewing and surface.strips[0].text[0] == "Lights")
        await until(lambda: daemon.bridge is not None and daemon.bridge.ready and daemon.bridge.entity_count == 11)
        assert lights in broker.retained

        # stopping during a preview leaves the file as it was
        _, writer = await asyncio.open_unix_connection(socket)
        writer.write(live.encode_request(StartPreview(HOME_ASSISTANT.replace("Lights", "Desk"))))
        await until(lambda: daemon.previewing)
        daemon.stop()
        await task
        writer.close()
    assert config_path.read_text() == HOME_ASSISTANT
