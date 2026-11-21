"""
The virtual twin on its own, without a daemon: its backend, its hands and what it does with its configuration.
"""

import asyncio

import pytest

from tests.support.waiting import until
from xtouch_daemon.audio.model import Direction
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.runtime.twin import Twin, TwinBackend
from xtouch_daemon.slots.outcomes import Situation
from xtouch_daemon.slots.world import DEFAULT_OUTPUT, Names

CONFIG = """
[channel.out]
type = "output"
label = "Out"
color = "cyan"

[channel.game]
type = "apps"
match = ["mygame"]
label = "Game"

[state.gaming]
mode = true

[switching]
chord_action = "cycle_modes"
banner = 0

[slots]
1 = "out"
2 = ["game if gaming", "auto"]
"""
HOME = Situation("default", frozenset(), frozenset(), apps=1)


async def test_a_twin_steps_and_shows_its_strips():
    twin = Twin(parse_config(CONFIG), HOME, Names(apps=("Firefox",)))
    assert twin.view() is None
    task = asyncio.create_task(twin.run())
    try:
        await until(lambda: twin.view() is not None)
        view = twin.view()
        assert view is not None
        assert view.strips[0].text[0] == "Out"
        assert view.strips[1].text[0] == "Firefox"
        # a hand on the fader moves the twin's sound server, nothing else
        twin.play(protocol.FaderTouched(0, True))
        twin.play(protocol.FaderMoved(0, protocol.fader_value(0.25)))
        await until(lambda: twin.sound.state.outputs[0].volume != 100)
        twin.play(protocol.ButtonPressed(0, protocol.Button.MUTE, True))
        twin.play(protocol.EncoderTurned(0, 1))
        twin.play(protocol.EncoderPressed(0, True))
        twin.play(protocol.EncoderPressed(0, False))
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        twin.close()
        await twin.wait_closed()


async def test_a_twin_follows_a_new_situation_configuration_and_names():
    twin = Twin(parse_config(CONFIG), HOME)
    task = asyncio.create_task(twin.run())
    try:
        await until(lambda: twin.view() is not None)
        twin.set_situation(Situation("gaming", frozenset(), frozenset(), apps=1))
        await until(lambda: (view := twin.view()) is not None and view.slots.mode == "gaming")
        twin.set_names(Names(apps=("Spotify",)))
        await until(
            lambda: (view := twin.view()) is not None and any(strip.text[0] == "Spotify" for strip in view.strips)
        )
        twin.reconfigure(parse_config(CONFIG.replace('"Out"', '"Boxes"')))
        await until(lambda: (view := twin.view()) is not None and view.strips[0].text[0] == "Boxes")
        # the chord changes nothing: the situation is the GUI's
        twin._on_chord()
        assert twin.slots.mode == "gaming"
    finally:
        task.cancel()
        twin.close()
        await twin.wait_closed()


async def test_the_backend_is_in_memory_and_keeps_what_the_strips_set():
    changed = []
    backend = TwinBackend(changed.append)
    twin = Twin(parse_config(CONFIG), HOME)
    backend.set_state(twin.sound.state)
    twin.close()
    twin = Twin(parse_config(CONFIG), HOME, Names(apps=("Firefox",)))
    backend.set_state(twin.sound.state)
    await backend.set_device_volume(Direction.OUTPUT, DEFAULT_OUTPUT, 40)
    await backend.set_device_mute(Direction.OUTPUT, DEFAULT_OUTPUT, True)
    await backend.set_device_balance(Direction.OUTPUT, DEFAULT_OUTPUT, 0.5)
    await backend.set_default(Direction.OUTPUT, DEFAULT_OUTPUT)
    await backend.set_default(Direction.INPUT, "x")
    await backend.set_card_profile("card", "profile")
    index = backend.state.streams[0].index
    await backend.set_stream_volume(index, 30)
    await backend.set_stream_mute(index, True)
    await backend.set_stream_balance(index, -0.5)
    assert changed
    output = backend.state.outputs[0]
    assert (output.volume, output.muted, output.balance) == (40, True, 0.5)
    # a new world keeps the volumes of what is still there
    backend.set_state(twin.sound.state)
    assert backend.state.outputs[0].volume == 40
    assert backend.state.streams[0].volume == 30
    with pytest.raises(NotImplementedError):
        await backend.run(lambda state: None)
    twin.close()


async def test_a_twin_shows_parts_in_home_assistant_as_offline():
    """The twin has no MQTT: an audio channel with parts in Home Assistant runs, as while it is not there."""
    config = parse_config(
        CONFIG.replace('color = "cyan"', 'color = "homeassistant"\nlcd = "homeassistant"\nencoder = "homeassistant"')
        + '\n[mqtt]\nhost = "broker"\n'
    )
    twin = Twin(config, HOME)
    task = asyncio.create_task(twin.run())
    try:
        await until(lambda: (view := twin.view()) is not None and tuple(view.strips[0].text) == ("Out", "offline"))
        twin.play(protocol.EncoderTurned(0, 1))
        await asyncio.sleep(0.05)
        view = twin.view()
        assert view is not None
        assert tuple(view.strips[0].text) == ("Out", "offline")
    finally:
        task.cancel()
        twin.close()
        await twin.wait_closed()
