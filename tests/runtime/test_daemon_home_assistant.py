"""
The daemon with Home Assistant: the MQTT bridge across reloads.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend
from tests.support.daemon import HOME_ASSISTANT, QUIET, STATE, Notifications, make, make_with_mqtt
from tests.support.hardware import RecordingSurface
from tests.support.mqtt import FakeBroker
from tests.support.waiting import until
from xtouch_daemon import __version__
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.live.codec import decode
from xtouch_daemon.live.messages import (
    fingerprint,
)
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.daemon import Daemon


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
    await until(
        lambda: "STATUS=waiting for X-Touch-Ext, waiting for the sound server, MQTT connected" in notifications.states()
    )
    # the slots show once the sound server tells what plays
    assert backend.on_state is not None
    backend.on_state(STATE)
    await until(lambda: surface.strips[0].text == ["Lights", ""])

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
            capture_command=QUIET,
            bridge=MqttBridge(config.mqtt, client_factory=broker.client),
            live_socket=socket,
        )
        task = asyncio.create_task(daemon.run())
        await until(lambda: backend.on_state is not None)
        assert backend.on_state is not None
        backend.on_state(STATE)
        await until(lambda: surface.strips[0].text == ["Lights", ""] and daemon.bridge and daemon.bridge.connected)
        await until(socket.exists)

        reader, writer = await asyncio.open_unix_connection(socket)
        snapshot = decode(await reader.readline())
        assert snapshot is not None
        assert snapshot.config == fingerprint(config)
        assert (snapshot.device, snapshot.sound_server, snapshot.mqtt) == (False, True, True)
        state = snapshot.mqtt_state
        assert state is not None
        assert (state.broker, state.username, state.connected, state.error, state.entities) == (
            "broker:1883",
            None,
            True,
            None,
            21,
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
    assert Daemon(config, backend, surface, capture_command=QUIET).bridge is not None


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
    await until(lambda: backend.on_state is not None)
    assert backend.on_state is not None
    backend.on_state(STATE)
    await until(lambda: surface.strips[0].text == ["Lights", ""])

    config_path.write_text(HOME_ASSISTANT.replace("lights", "desk"))
    assert daemon.reload()
    await until(lambda: "homeassistant/number/xtouch/desk_fader/config" in broker.retained)
    daemon.stop()
    await task

    assert "homeassistant/number/xtouch/lights_fader/config" not in broker.retained
