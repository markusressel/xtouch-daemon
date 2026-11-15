import asyncio
import logging
import os
import signal
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from tests.conftest import FakeBackend, RecordingSurface, finish_tasks, output, settle
from tests.fake_mqtt import FakeBroker
from xtouch_daemon import daemon as daemon_module
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon import protocol
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config import Config, parse_config
from xtouch_daemon.daemon import Daemon
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


def quiet_mixer(surface: Surface, backend: AudioBackend, config: Config, *, bridge: MqttBridge | None) -> Mixer:
    # meters that capture nothing: the tests don't touch the audio of the machine they run on
    return Mixer(surface, backend, config, capture_command="true", bridge=bridge)


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


async def test_a_changed_device_section_needs_a_restart(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    caplog: pytest.LogCaptureFixture,
) -> None:
    daemon = make(config_path, surface, backend)

    config_path.write_text('[device]\nname = "X-Touch"\n' + SPEAKER)
    assert daemon.reload()

    assert "restart the daemon" in caplog.text
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


async def test_without_mqtt_section_there_is_no_bridge(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend
) -> None:
    assert make(config_path, surface, backend).bridge is None
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
