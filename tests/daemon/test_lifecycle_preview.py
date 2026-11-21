"""
The live preview of the GUI in the daemon: unsaved configurations on the device for a while.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend
from tests.support.daemon import HOME_ASSISTANT, QUIET, SPEAKER, STATE, Notifications, make_with_mqtt
from tests.support.hardware import RecordingSurface
from tests.support.mqtt import FakeBroker
from tests.support.tasks import settle
from tests.support.waiting import until
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.daemon import lifecycle as daemon_module
from xtouch_daemon.daemon.lifecycle import Daemon
from xtouch_daemon.hardware.protocol import Color
from xtouch_daemon.live.codec import decode, decode_message, encode_request
from xtouch_daemon.live.messages import (
    FEATURES,
    EndPreview,
    KeepPreview,
    Reply,
    StartPreview,
    fingerprint,
)
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.slots.outcomes import Situation

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
        capture_command=QUIET,
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
    assert daemon.snapshot().features == FEATURES
    assert not daemon.snapshot().preview

    assert daemon.on_request(gui, StartPreview(BOXES)) == Reply("preview", True)

    assert surface.strips[0].text == ["Boxes", "50%"]
    assert config_path.read_text() == SPEAKER
    assert daemon.previewing
    assert daemon.mixer.preview
    snapshot = daemon.snapshot()
    assert snapshot.preview
    assert snapshot.config == fingerprint(parse_config(BOXES))
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
    reply = daemon.on_request(gui, StartPreview('[channel.x]\ntype = "loud"\n'))
    assert reply is not None
    assert not reply.ok
    assert reply.message.startswith("The previewed configuration has errors:\n  channel.x.type")
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
        "preview", True, "The device name and virtual change when the file is saved."
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
    assert told.reasons(first) == ["another window previews on the device now"]
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
    config_path.write_text('[channel.x]\ntype = "loud"\n')
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
            capture_command=QUIET,
            bridge=MqttBridge(config.mqtt, client_factory=broker.client),
            live_socket=socket,
        )
        task = asyncio.create_task(daemon.run())
        await until(lambda: backend.on_state is not None)
        assert backend.on_state is not None
        backend.on_state(STATE)
        await until(lambda: daemon.bridge is not None and daemon.bridge.ready and socket.exists())
        lights = "homeassistant/number/xtouch/lights_fader/config"
        assert lights in broker.retained

        reader, writer = await asyncio.open_unix_connection(socket)
        # a preview without the Home Assistant channel: its entities stay in Home Assistant
        writer.write(encode_request(StartPreview(SPEAKER + '[mqtt]\nhost = "broker"\n')))
        while not isinstance(reply := decode_message(await reader.readline()), Reply):
            pass
        assert reply == Reply("preview", True)
        await until(lambda: surface.strips[0].text[0] == "Speaker")
        snapshot = None
        while snapshot is None or not snapshot.preview:
            snapshot = decode(await reader.readline())
        await until(lambda: daemon.bridge is not None and daemon.bridge.ready)
        assert lights in broker.retained

        # the GUI closed: back to the file, with the entities as they were
        writer.close()
        await until(lambda: not daemon.previewing and surface.strips[0].text[0] == "Lights")
        await until(lambda: daemon.bridge is not None and daemon.bridge.ready and daemon.bridge.entity_count == 21)
        assert lights in broker.retained

        # stopping during a preview leaves the file as it was
        _, writer = await asyncio.open_unix_connection(socket)
        writer.write(encode_request(StartPreview(HOME_ASSISTANT.replace("Lights", "Desk"))))
        await until(lambda: daemon.previewing)
        daemon.stop()
        await task
        writer.close()
    assert config_path.read_text() == HOME_ASSISTANT


async def test_a_preview_shows_a_situation_of_the_gui_and_the_real_one_again(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    daemon, _ = make_previewing(config_path, surface, backend, monkeypatch)
    gui = object()
    gaming = SPEAKER + "[state.gaming]\nmode = true\n"

    assert daemon.on_request(gui, StartPreview(gaming, Situation("nomode", frozenset(), frozenset()))) == Reply(
        "preview", False, "No mode nomode in the configuration."
    )
    assert not daemon.previewing
    assert daemon.on_request(gui, StartPreview(gaming, Situation("gaming", frozenset(), frozenset()))) == Reply(
        "preview", True
    )
    assert (slots := daemon.snapshot().slots) is not None
    assert slots.mode == "gaming"
    # the same configuration in the real situation: only the situation changes
    mixer = daemon.mixer
    assert daemon.on_request(gui, StartPreview(gaming)) == Reply("preview", True)
    assert daemon.mixer is mixer
    assert (slots := daemon.snapshot().slots) is not None
    assert slots.mode == "default"
    daemon.mixer.close()
    await settle()
