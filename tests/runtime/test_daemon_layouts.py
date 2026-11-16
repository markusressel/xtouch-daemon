"""
Layouts in the daemon: switching by hand, by rules and by the chord, and what it remembers.
"""

import asyncio
import json
import logging
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend, stream
from tests.support.daemon import SPEAKER, STATE, Notifications, quiet_mixer, until
from tests.support.hardware import RecordingSurface
from tests.support.mqtt import FakeBroker
from tests.support.tasks import settle
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import (
    EndPreview,
    Reply,
    StartPreview,
    SwitchLayout,
    VoipState,
)
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime import daemon as daemon_module
from xtouch_daemon.runtime.daemon import Daemon

LAYOUTS = (
    SPEAKER
    + """
[switching]
hold = 0
banner = 0.05

[voip]
provider = "demo"
participants = ["Ann"]

[[layout]]
name = "gaming"
label = "Gaming"
apps = ["steam_app_"]

[[layout.strip]]
type = "voip"

[[layout]]
name = "voice"
processes = ["mumble"]

[[layout.strip]]
type = "inherit"
"""
)


GAME = AudioState(outputs=STATE.outputs, default_output="speaker", streams=(stream(1, "steam_app_9", "wine"),))


def make_layouts(config_path: Path, surface: RecordingSurface, backend: FakeBackend, **options: object) -> Daemon:
    config_path.write_text(LAYOUTS)
    return Daemon(
        parse_config(LAYOUTS),
        backend,
        surface,
        config_path,
        mixer_factory=quiet_mixer,
        **options,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    )


async def test_switching_layouts_by_hand(
    config_path: Path, surface: RecordingSurface, notifications: Notifications, caplog: pytest.LogCaptureFixture
) -> None:
    daemon = make_layouts(config_path, surface, FakeBackend((STATE,)))
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Speaker", "50%"])
    assert daemon.layout == "default"
    assert daemon.snapshot().layouts == ("default", "gaming", "voice")
    # the demo people of [voip], none of them on a strip of the default layout
    assert daemon.snapshot().voip == VoipState("demo", True, None, None, 1, ("Ann",), (None,) * 8)

    assert daemon.switch_layout("gaming")
    assert not daemon.switch_layout("gaming")
    assert daemon.mixer.layout == "gaming"
    # the banner names the layout and why, the strips draw underneath
    assert surface.strips[3].shown_text == ("    Gam", "    man")
    assert surface.strips[0].text == ["Ann", "100%"]
    assert daemon.snapshot().layout == "gaming"
    voip = daemon.snapshot().voip
    assert voip is not None
    assert voip.strips[0] == "Ann"
    await until(lambda: surface.strips[3].overlay is None)

    gui = object()
    assert daemon.on_request(gui, SwitchLayout("+1")) == Reply("layout", True, "voice")
    assert daemon.layout == "voice"
    # the inherited strip
    assert surface.strips[0].text == ["Speaker", "50%"]
    daemon.on_request(gui, SwitchLayout("-1"))
    assert daemon.layout == "gaming"
    daemon.on_request(gui, SwitchLayout("default"))
    assert daemon.layout == "default"
    assert daemon.on_request(gui, SwitchLayout("nope")) == Reply(
        "layout", False, "There is no layout nope (default, gaming, voice)"
    )
    assert daemon.layout == "default"
    with pytest.raises(KeyError):
        daemon.switch_layout("nope")

    daemon.stop()
    await task


async def test_a_chord_of_solo_buttons_switches_to_the_next_layout(
    config_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    daemon = make_layouts(config_path, surface, FakeBackend((STATE,)))
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Speaker", "50%"])

    def press(strip: int, button: Button, pressed: bool = True) -> None:
        surface.on_event(protocol.ButtonPressed(strip, button, pressed))

    press(0, Button.SOLO)
    press(7, Button.MUTE)
    press(3, Button.SOLO)
    assert daemon.layout == "default"
    press(7, Button.SOLO)
    assert daemon.layout == "gaming"
    # still held: once per chord
    press(7, Button.SOLO, False)
    press(7, Button.SOLO)
    assert daemon.layout == "gaming"
    press(0, Button.SOLO, False)
    press(7, Button.SOLO, False)
    press(7, Button.SOLO)
    press(0, Button.SOLO)
    assert daemon.layout == "voice"
    assert "".join(strip.shown_text[1] for strip in surface.strips).strip() == "buttons"

    daemon.stop()
    await task


async def test_rules_switch_layouts(
    config_path: Path,
    surface: RecordingSurface,
    backend: FakeBackend,
    notifications: Notifications,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daemon_module, "RULES_INTERVAL", 0.005)
    running: set[str] = set()
    daemon = make_layouts(config_path, surface, backend, processes=lambda: frozenset(running))
    task = asyncio.create_task(daemon.run())
    await until(lambda: backend.on_state is not None)
    assert backend.on_state is not None
    backend.on_state(GAME)
    assert daemon.layout == "gaming"
    backend.on_state(STATE)
    await until(lambda: daemon.layout == "default")
    running.add("mumble")
    await until(lambda: daemon.layout == "voice")
    # a sound server that is gone tells nothing about the applications
    backend.on_state(DISCONNECTED)
    assert daemon.layout == "voice"

    daemon.stop()
    await task


async def test_without_rules_processes_are_not_looked_at(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_module, "RULES_INTERVAL", 0.001)
    asked: list[int] = []

    def processes() -> frozenset[str]:
        asked.append(1)
        return frozenset()

    text = '[[layout]]\nname = "a"\napps = ["x"]\n'
    config_path.write_text(text)
    daemon = Daemon(parse_config(text), backend, surface, config_path, mixer_factory=quiet_mixer, processes=processes)
    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.02)
    assert asked == []
    daemon.stop()
    await task
    plain = Daemon(parse_config(""), backend, surface, mixer_factory=quiet_mixer)
    assert not plain.switcher.has_rules
    task = asyncio.create_task(plain.run())
    await asyncio.sleep(0.02)
    plain.stop()
    await task


async def test_a_reload_keeps_the_layout_if_it_is_still_there(
    config_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    daemon = make_layouts(config_path, surface, FakeBackend((STATE,)))
    task = asyncio.create_task(daemon.run())
    await until(lambda: surface.strips[0].text == ["Speaker", "50%"])
    voip = daemon.voip
    daemon.switch_layout("voice")
    assert daemon.reload()
    assert daemon.layout == "voice"
    # the same [voip]: the same provider
    assert daemon.voip is voip

    config_path.write_text(SPEAKER + '[voip]\nprovider = "demo"\nparticipants = ["Bob"]\n')
    assert daemon.reload()
    assert daemon.layout == "default"
    assert daemon.voip is not voip
    config_path.write_text(SPEAKER)
    assert daemon.reload()
    assert daemon.voip is None

    daemon.stop()
    await task


async def test_without_a_banner_the_strips_show_at_once(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend
) -> None:
    text = LAYOUTS.replace("banner = 0.05", "banner = 0")
    config_path.write_text(text)
    daemon = Daemon(parse_config(text), backend, surface, config_path, mixer_factory=quiet_mixer)
    daemon.mixer.on_state(STATE)
    daemon.switch_layout("voice")
    assert surface.strips[0].overlay is None
    # a new [voip] before the daemon runs: it starts with the daemon
    config_path.write_text(SPEAKER)
    assert daemon.reload()
    assert daemon.voip is None


def test_the_entities_of_every_layout() -> None:
    config = parse_config(
        '[mqtt]\nhost = "b"\n[[strip]]\ntype = "homeassistant"\nid = "a"\n'
        '[[layout]]\nname = "x"\n[[layout.strip]]\ntype = "output"\nfader = "homeassistant"\nid = "b"\n'
        '[[layout.strip]]\ntype = "output"\nchoices = [{ device = "a" }, { device = "b" }]\n'
    )
    ids = daemon_module.layout_entity_ids(config, "ns")
    # the select of the choices, by its place
    assert "ns_strip_2_output" in ids
    assert "ns_a_fader" in ids
    assert "ns_b_fader" in ids
    assert "ns_b_encoder" not in ids


def test_a_strip_inherited_from_another_place_keeps_its_entities() -> None:
    config = parse_config(
        '[mqtt]\nhost = "b"\n[[strip]]\ntype = "auto"\n[[strip]]\ntype = "homeassistant"\n'
        '[[layout]]\nname = "x"\n[[layout.strip]]\ntype = "inherit"\nstrip = 2\n'
    )
    # the entities of its place in the default layout, once
    assert {unique_id for unique_id in daemon_module.layout_entity_ids(config, "ns") if "strip_1" in unique_id} == set()
    assert config.entity_strips("x")[0][1] == config.entity_strips()[0][1] == "strip_2"


async def test_home_assistant_chooses_the_layout(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, broker: FakeBroker
) -> None:
    text = LAYOUTS + '\n[mqtt]\nhost = "broker"\n' + '[[layout.strip]]\ntype = "homeassistant"\nid = "lamp"\n'
    config_path.write_text(text)
    config = parse_config(text)
    assert config.mqtt is not None
    daemon = Daemon(
        config,
        backend,
        surface,
        config_path,
        mixer_factory=quiet_mixer,
        bridge=MqttBridge(config.mqtt, client_factory=broker.client),
    )
    task = asyncio.create_task(daemon.run())
    select = "homeassistant/select/xtouch/layout"
    await until(lambda: broker.retained.get(f"{select}/state") == "default")
    discovery = json.loads(broker.retained[f"{select}/config"])
    assert discovery["options"] == ["default", "gaming", "voice"]

    broker.publish(f"{select}/set", "voice")
    await until(lambda: daemon.layout == "voice")
    assert "homeassistant/number/xtouch/lamp_fader/config" in broker.retained

    daemon.switch_layout("gaming")
    await until(lambda: broker.retained.get(f"{select}/state") == "gaming")
    # the entities of the layout that went stay in Home Assistant
    await until(lambda: daemon.bridge is not None and daemon.bridge.ready)
    assert "homeassistant/number/xtouch/lamp_fader/config" in broker.retained
    broker.publish(f"{select}/set", "nope")
    await asyncio.sleep(0.02)
    assert daemon.layout == "gaming"

    # a reload brings a new select (with the layouts of the new file)
    assert daemon.reload()
    assert daemon.layout == "gaming"
    broker.publish(f"{select}/set", "voice")
    await until(lambda: daemon.layout == "voice")

    daemon.stop()
    await task


async def test_a_preview_has_layouts_too(
    config_path: Path, surface: RecordingSurface, backend: FakeBackend, broker: FakeBroker
) -> None:
    text = LAYOUTS + '\n[mqtt]\nhost = "broker"\n' + '[[layout.strip]]\ntype = "homeassistant"\nid = "lamp"\n'
    config_path.write_text(text)
    config = parse_config(text)
    assert config.mqtt is not None
    daemon = Daemon(
        config,
        backend,
        surface,
        config_path,
        mixer_factory=quiet_mixer,
        bridge=MqttBridge(config.mqtt, client_factory=broker.client),
    )
    task = asyncio.create_task(daemon.run())
    select = "homeassistant/select/xtouch/layout"
    await until(lambda: broker.retained.get(f"{select}/state") == "default")
    daemon.switch_layout("voice")
    gui = object()

    # a preview that adds a layout: the one shown stays, Home Assistant offers the new one
    preview = text + '\n[[layout]]\nname = "music"\n\n[[layout.strip]]\ntype = "empty"\n'
    assert daemon.on_request(gui, StartPreview(preview)) == Reply("preview", True)
    assert daemon.layout == "voice"
    assert daemon.snapshot().layouts == ("default", "gaming", "voice", "music")
    await until(lambda: json.loads(broker.retained[f"{select}/config"])["options"][-1:] == ["music"])
    # the GUI shows it on the device: still a preview
    assert daemon.on_request(gui, SwitchLayout("music")) == Reply("layout", True, "music")
    assert daemon.mixer.layout == "music"
    assert daemon.mixer.preview
    assert daemon.snapshot().preview
    assert "homeassistant/number/xtouch/lamp_fader/config" in broker.retained

    # back to the file, which does not have it: the default layout
    assert daemon.on_request(gui, EndPreview()) is None
    assert not daemon.mixer.preview
    assert daemon.layout == "default"
    assert daemon.snapshot().layouts == ("default", "gaming", "voice")
    await until(lambda: json.loads(broker.retained[f"{select}/config"])["options"] == ["default", "gaming", "voice"])
    # the entities of the other layouts stay
    await until(lambda: daemon.bridge is not None and daemon.bridge.ready)
    assert "homeassistant/number/xtouch/lamp_fader/config" in broker.retained

    daemon.stop()
    await task


async def test_the_layout_chosen_last_comes_back_after_a_restart(
    config_path: Path, surface: RecordingSurface, broker: FakeBroker, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    remembered = tmp_path / "state" / "layout"
    text = LAYOUTS + '\n[mqtt]\nhost = "broker"\n'
    config_path.write_text(text)
    config = parse_config(text)
    assert config.mqtt is not None

    def start(state: AudioState, processes: frozenset[str] = frozenset()) -> Daemon:
        assert config.mqtt is not None
        return Daemon(
            config,
            FakeBackend((state,)),
            surface,
            config_path,
            mixer_factory=quiet_mixer,
            bridge=MqttBridge(config.mqtt, client_factory=broker.client),
            processes=lambda: processes,
            layout_file=remembered,
        )

    daemon = start(STATE)
    assert daemon.layout == "default"
    task = asyncio.create_task(daemon.run())
    select = "homeassistant/select/xtouch/layout"
    await until(lambda: broker.retained.get(f"{select}/state") == "default")
    # by hand: kept
    daemon.switch_layout("voice")
    assert remembered.read_text() == "voice\n"
    # by a rule: not kept, the choice by hand is
    daemon._on_state(GAME)  # pyright: ignore[reportPrivateUsage]
    assert daemon.layout == "gaming"
    await until(lambda: broker.retained.get(f"{select}/state") == "gaming")
    assert remembered.read_text() == "voice\n"
    daemon.stop()
    await task

    # the next start shows it, and Home Assistant (which still has the one of the rule) learns it
    daemon = start(STATE)
    assert daemon.layout == "voice"
    assert "Showing the layout voice of the last run" in caplog.text
    task = asyncio.create_task(daemon.run())
    await until(lambda: broker.retained.get(f"{select}/state") == "voice")
    assert daemon.layout == "voice"
    # the rules ended (the game is over): the default layout, which is kept too
    daemon._on_state(GAME)  # pyright: ignore[reportPrivateUsage]
    daemon._on_state(STATE)  # pyright: ignore[reportPrivateUsage]
    assert daemon.layout == "default"
    assert remembered.read_text() == "default\n"
    daemon.switch_layout("voice")
    daemon.stop()
    await task

    # a rule that matches at the start wins
    daemon = start(GAME)
    assert daemon.layout == "voice"
    task = asyncio.create_task(daemon.run())
    await until(lambda: daemon.layout == "gaming")
    daemon.stop()
    await task
    assert remembered.read_text() == "voice\n"

    # a layout that is not there anymore
    remembered.write_text("music\n")
    assert start(STATE).layout == "default"
    assert "The layout music of the last run is not in the configuration anymore" in caplog.text
    remembered.write_text("")
    assert start(STATE).layout == "default"


async def test_the_layout_is_kept_only_where_it_can_be(
    config_path: Path, surface: RecordingSurface, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # a directory where the file should be: neither read nor written
    remembered = tmp_path / "layout"
    remembered.mkdir()
    daemon = make_layouts(config_path, surface, FakeBackend((STATE,)), layout_file=remembered)
    assert daemon.layout == "default"
    assert "Can't read the layout of the last run" in caplog.text
    daemon.switch_layout("gaming")
    assert "Can't keep the layout for the next start" in caplog.text
    daemon.mixer.close()
    await settle()
