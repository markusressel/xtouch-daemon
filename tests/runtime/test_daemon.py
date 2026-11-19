"""
The lifecycle of the daemon: starting, reloading, the device coming and going, stopping.
"""

import asyncio
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend
from tests.support.daemon import QUIET, SPEAKER, STATE, Notifications, make
from tests.support.hardware import RecordingSurface
from tests.support.tasks import settle
from tests.support.waiting import until
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import strip as strip_module
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.hardware.transport import SocketPort
from xtouch_daemon.runtime import daemon as daemon_module
from xtouch_daemon.runtime.daemon import Daemon, device_surface


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
    assert daemon.mixer.desk.meters[0].targets == set()


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
    monkeypatch.setattr(strip_module, "FADER_SLOW_SMOOTH_TIME", 0.3)

    os.kill(os.getpid(), signal.SIGINT)
    await until(lambda: "STOPPING=1" in notifications.states())
    os.kill(os.getpid(), signal.SIGINT)
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, 5)

    assert "Stopping already" in caplog.text
    assert surface.faders(0)[-1] == 0
    assert surface.strips[0].text == ["", ""]


async def test_sighup_loads_the_configuration_again(
    config_path: Path, surface: RecordingSurface, notifications: Notifications, monkeypatch: pytest.MonkeyPatch
) -> None:
    # not the watch of the file
    monkeypatch.setattr(daemon_module, "FILE_CHECK", 3600.0)
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


async def test_a_changed_file_is_loaded_once_it_rests(
    config_path: Path,
    surface: RecordingSurface,
    notifications: Notifications,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(daemon_module, "FILE_CHECK", 0.05)
    daemon = make(config_path, surface, FakeBackend((STATE,)))
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text[0] == "Speaker")

    # saved in an editor
    config_path.write_text(SPEAKER.replace('"Speaker"', '"Boxes"'))
    await until(lambda: surface.strips[0].text[0] == "Boxes")
    assert caplog.text.count("The configuration file changed, loading it") == 1

    # saved by the GUI, which reloads the daemon itself: loaded once
    config_path.write_text(SPEAKER.replace('"Speaker"', '"Desk"'))
    daemon.reload()
    # a file with errors: the configuration stays; a file that is gone is no change
    config_path.write_text('[channel.x]\ntype = "loud"\n')
    await until(lambda: "Keeping the current configuration" in caplog.text)
    config_path.unlink()
    await asyncio.sleep(0.3)
    daemon.stop()
    await task

    assert surface.strips[0].text == ["", ""]
    assert caplog.text.count("The configuration file changed, loading it") == 2
    assert daemon.file_config == parse_config(SPEAKER.replace('"Speaker"', '"Desk"'))


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

    config_path.write_text('[channel.x]\ntype = "loud"\n')
    assert not daemon.reload()

    assert daemon.mixer is old
    assert "Keeping the current configuration" in caplog.text
    assert notifications[-1] == ("READY=1", "STATUS=Configuration has errors, see the log")


async def test_the_options_of_the_device_apply_with_a_reload(
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

    # another device too: the surface lets go of the one it has and connects to that one
    config_path.write_text('[device]\nname = "X-Touch"\n' + SPEAKER)
    assert daemon.reload()
    await settle()
    assert surface.device_name == "X-Touch"
    config_path.write_text("[device]\nvirtual = true\n" + SPEAKER)
    assert daemon.reload()
    await settle()
    assert isinstance(surface.port, SocketPort)

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
    from xtouch_daemon.hardware.protocol import Button, ButtonPressed

    daemon = make(config_path, surface, backend)
    daemon.reload()
    daemon.mixer.on_state(STATE)
    daemon.step()

    surface.on_event(ButtonPressed(0, Button.MUTE, True))
    await settle()

    assert backend.calls[-1][0] == "set_device_mute"
    daemon.mixer.close()


async def test_a_daemon_without_surface_makes_one_for_the_configured_device(backend: FakeBackend) -> None:
    daemon = Daemon(parse_config('[device]\nname = "X-Touch"\n'), backend)

    assert daemon.surface.device_name == "X-Touch"
    logging.getLogger().debug("no tasks were started")


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
        capture_command=QUIET,
        players=players,  # type: ignore[arg-type]
    )
    assert daemon.mixer.channels["speaker"].env.players is players
    task = asyncio.create_task(daemon.run())
    await asyncio.wait_for(players.running.wait(), 1)
    assert daemon.reload()
    assert daemon.mixer.channels["speaker"].env.players is players
    daemon.stop()
    await task


def test_the_live_view_tells_whether_the_device_is_the_virtual_one(config_path: Path) -> None:
    config = parse_config(config_path.read_text())
    real = Daemon(config, FakeBackend(), RecordingSurface(), config_path, capture_command=QUIET)
    virtual = Daemon(
        config, FakeBackend(), device_surface("X-Touch-Ext", virtual=True), config_path, capture_command=QUIET
    )

    assert not real.snapshot().virtual
    assert virtual.snapshot().virtual
