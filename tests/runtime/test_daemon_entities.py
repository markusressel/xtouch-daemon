"""
The daemon with the API of Home Assistant (`[homeassistant]`): one connection while the configuration (or a twin) has
parts bound to entities, across reloads, and for the live view. Home Assistant is the one in memory.
"""

import asyncio
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend
from tests.support.daemon import QUIET, STATE, Notifications
from tests.support.hardware import RecordingSurface
from tests.support.homeassistant import FakeHomeAssistant
from tests.support.waiting import until
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.homeassistant.client import HomeAssistant
from xtouch_daemon.live.codec import decode, encode
from xtouch_daemon.live.messages import HomeAssistantState, Reply, StartPreview
from xtouch_daemon.runtime.daemon import Daemon
from xtouch_daemon.slots.outcomes import Situation
from xtouch_daemon.system.commands import SimulatedCommands

SECTION = '[homeassistant]\nurl = "http://ha.test:8123"\ntoken = "the-token"\n'
CHANNEL = """
[channel.speaker]
type = "output"
device = "speaker"
label = "Speaker"
lcd = { entity = "sensor.temperature" }

[slots]
1 = "speaker"
"""
PLAIN = CHANNEL.replace('lcd = { entity = "sensor.temperature" }\n', "")


@pytest.fixture
def home() -> FakeHomeAssistant:
    home = FakeHomeAssistant()
    home.set("sensor.temperature", "21.5", unit_of_measurement="°C")
    return home


def made(config_path: Path, surface: RecordingSurface, backend: FakeBackend, home: FakeHomeAssistant) -> Daemon:
    return Daemon(
        parse_config(config_path.read_text()),
        backend,
        surface,
        config_path,
        capture_command=QUIET,
        live_socket=config_path.with_name("live.sock"),
        hass=HomeAssistant(home.connect),
    )


async def test_the_daemon_connects_while_parts_show_entities(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    home: FakeHomeAssistant,
    notifications: Notifications,
) -> None:
    config_path.write_text(SECTION + CHANNEL)
    daemon = made(config_path, surface, backend, home)
    assert daemon.commands.hass is daemon.hass
    task = asyncio.create_task(daemon.run())
    await until(lambda: backend.on_state is not None)
    assert backend.on_state is not None
    backend.on_state(STATE)
    await until(lambda: surface.strips[0].text == ["Speaker", "21.5°C"])
    state = daemon.snapshot().homeassistant
    assert state == HomeAssistantState(
        url="http://ha.test:8123",
        connected=True,
        synced=True,
        error=None,
        entities=1,
        watched=1,
        version="2026.11.0",
    )
    # the live view carries it
    decoded = decode(encode(daemon.snapshot()))
    assert decoded is not None
    assert getattr(decoded, "homeassistant", None) == state
    home.set("sensor.temperature", "22", unit_of_measurement="°C")
    await until(lambda: surface.strips[0].text == ["Speaker", "22°C"])

    # without entities: no connection
    config_path.write_text(SECTION + PLAIN)
    assert daemon.reload()
    await until(lambda: not home.connected)
    assert daemon.snapshot().homeassistant is None
    assert "Home Assistant" not in notifications[-1][-1]
    # entities again, with another token: it connects with that one
    home.token = "another"
    config_path.write_text(SECTION.replace("the-token", "another") + CHANNEL)
    assert daemon.reload()
    await until(lambda: daemon.hass.synced)
    # the status line follows the connection, not only the reloads
    assert notifications[-1][-1].endswith(", Home Assistant connected")
    home.disconnect()
    await until(lambda: notifications[-1][-1].endswith(", waiting for Home Assistant"))
    assert len(home.connections) == 2
    daemon.stop()
    await task
    assert not home.connected
    assert daemon.hass.config is None


async def test_a_section_without_entities_connects_nothing(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, home: FakeHomeAssistant
) -> None:
    config_path.write_text(SECTION + PLAIN)
    daemon = made(config_path, surface, backend, home)
    task = asyncio.create_task(daemon.run())
    await until(lambda: backend.on_state is not None)
    await asyncio.sleep(1)
    assert home.connections == []
    daemon.stop()
    await task


async def test_a_twin_with_entities_reads_them_but_calls_nothing(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, home: FakeHomeAssistant
) -> None:
    config_path.write_text(SECTION + PLAIN)
    daemon = made(config_path, surface, backend, home)
    task = asyncio.create_task(daemon.run())
    await until(lambda: backend.on_state is not None)
    gui = object()
    situation = Situation("default", frozenset(), frozenset())
    edited = SECTION + CHANNEL + '\n[channel.speaker.select]\npress = { service = "light.toggle" }\n'
    reply = daemon.on_request(gui, StartPreview(edited, situation, on_device=False))
    assert reply == Reply("preview", True)
    # the twin's entities: the daemon connects
    await until(lambda: daemon.hass.synced)
    twin = daemon._twins[gui].twin  # pyright: ignore[reportPrivateUsage]
    assert isinstance(twin.commands, SimulatedCommands)
    assert twin.commands.hass is daemon.hass
    await until(lambda: twin.surface.strips[0].text[1] == "21.5°C")
    # its controls call no services
    twin.mixer.controllers[0].on_button(Button.SELECT, True)
    await asyncio.sleep(0.1)
    assert home.calls == []
    # the twin goes: so does the connection
    daemon.on_client_closed(gui)
    await until(lambda: not home.connected)
    daemon.stop()
    await task
