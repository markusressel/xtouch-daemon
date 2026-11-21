"""
Parts bound to entities of Home Assistant, on a custom channel and on an audio strip: what they show of the entities,
the services a move or a press calls, and what they show while Home Assistant is not there. Home Assistant is the one
in memory (`tests/support/homeassistant.py`).
"""

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator

import pytest

from tests.support.audio import FakeBackend, output
from tests.support.hardware import RecordingSurface
from tests.support.homeassistant import FakeHomeAssistant, connected, hass_config
from tests.support.strips import build, strips_of
from tests.support.tasks import settle
from xtouch_daemon.audio.meter import Lit
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.strips import CustomStripConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import METER_MAX, Button, Color, Led, RingMode
from xtouch_daemon.homeassistant.client import HomeAssistant
from xtouch_daemon.strips.base import NOTICE_TIME, StripEnv, VolumeStrip
from xtouch_daemon.strips.custom import CustomStrip
from xtouch_daemon.strips.entity import EntityLine, EntityValue
from xtouch_daemon.system.commands import Commands, SimulatedCommands

SPEAKER = AudioState(outputs=(output("speaker", 50),))


@pytest.fixture
def home() -> FakeHomeAssistant:
    home = FakeHomeAssistant()
    home.set("light.desk", "on", brightness=51, rgb_color=[255, 0, 0], friendly_name="Desk")
    home.set("sensor.cpu", "45", unit_of_measurement="%")
    home.set("media_player.tv", "playing", volume_level=0.5, media_title="Song 2")
    return home


@pytest.fixture
async def hass(home: FakeHomeAssistant) -> AsyncIterator[HomeAssistant]:
    hass = await connected(home)
    yield hass
    await hass.close()


def custom(surface: RecordingSurface, env: StripEnv, commands: Commands, **options: object) -> CustomStrip:
    config = CustomStripConfig.model_validate({"type": "custom", "label": "Lamp"} | options)
    strip = build(config, surface.strips[0], dataclasses.replace(env, commands=commands))
    assert isinstance(strip, CustomStrip)
    strip.update(AudioState())
    return strip


async def test_a_fader_follows_and_sets_the_brightness_of_a_light(
    surface: RecordingSurface, env: StripEnv, home: FakeHomeAssistant, hass: HomeAssistant
) -> None:
    commands = Commands(hass)
    strip = custom(surface, env, commands, fader={"entity": "light.desk"})
    device = surface.strips[0]
    value = strip.fader_value()
    assert isinstance(value, EntityValue)
    assert (value.low, value.high) == (0, 255)
    assert device.fader == protocol.fader_value(51 / 255)
    assert device.text == ["Lamp", "51"]
    # a move: the service of the domain, with a whole brightness
    strip.on_touch(True)
    strip.on_fader(1.0)
    await settle()
    assert home.calls == [("light.turn_on", {"brightness": 255}, "light.desk")]
    # under the finger Home Assistant does not move the motor
    home.set("light.desk", "on", brightness=200)
    await settle()
    assert device.fader == protocol.fader_value(51 / 255)
    strip.on_touch(False)
    home.set("light.desk", "off")
    await settle()
    # off is the bottom
    assert value.value == 0
    assert device.fader == protocol.fader_value(0.0)
    # the encoder sets the fader's value in fine steps
    strip.on_encoder(2)
    await settle()
    # (2.55 a step: 1 % of the range)
    assert home.calls[-1] == ("light.turn_on", {"brightness": 5}, "light.desk")
    # gone: the value is not known
    home.disconnect()
    await settle()
    assert value.value is None
    assert device.text[1] == ""
    strip.close()
    await commands.wait_closed()
    assert hass.watched == 0


async def test_a_call_that_failed_moves_the_fader_back(
    surface: RecordingSurface,
    env: StripEnv,
    home: FakeHomeAssistant,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    commands = Commands(hass)
    strip = custom(surface, env, commands, fader={"entity": "light.desk"})
    value = strip.fader_value()
    assert value is not None
    home.failing["light.turn_on"] = "Entity light.desk is unavailable"
    strip.on_fader(1.0)
    assert value.value == 255
    await settle()
    assert home.calls == [("light.turn_on", {"brightness": 255}, "light.desk")]
    assert "Entity light.desk is unavailable" in caplog.text
    # Home Assistant did not take it: the fader is where the light is
    assert value.value == 51
    assert surface.strips[0].fader == protocol.fader_value(51 / 255)
    # a call that works leaves the fader where the hand put it, until the light tells its new brightness
    del home.failing["light.turn_on"]
    strip.on_fader(1.0)
    await settle()
    assert value.value == 255
    strip.close()
    await commands.wait_closed()


async def test_a_service_of_your_own_gets_the_value_in_its_data(
    surface: RecordingSurface,
    env: StripEnv,
    home: FakeHomeAssistant,
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    commands = Commands(hass)
    home.set("input_number.level", "4", min=0, max=8, step=1)
    await settle()
    encoder = {
        "entity": "input_number.level",
        "service": "script.level",
        "data": {"level": "{value}", "text": "at {value}"},
        "push": 2,
        "step": 1,
    }
    strip = custom(surface, env, commands, encoder=encoder)
    value = strip.encoder_value()
    assert value is not None
    # the range of the number
    assert (value.low, value.high) == (0, 8)
    assert surface.strips[0].ring == (6, RingMode.WRAP)
    strip.on_encoder(1)
    await settle()
    strip.on_encoder_press(True)
    await settle()
    assert home.calls == [
        ("script.level", {"level": 5, "text": "at 5"}, "input_number.level"),
        ("script.level", {"level": 2, "text": "at 2"}, "input_number.level"),
    ]
    # its range changes with the entity
    home.set("input_number.level", "4", min=0, max=16, step=1)
    await settle()
    assert (value.low, value.high) == (0, 16)
    home.failing["script.level"] = "no such script"
    strip.on_encoder(1)
    await settle()
    assert "Lamp.encoder: script.level on input_number.level: no such script" in caplog.text
    strip.close()
    await commands.wait_closed()


async def test_the_lcd_the_color_the_meter_and_the_leds_show_entities(
    surface: RecordingSurface, env: StripEnv, home: FakeHomeAssistant, hass: HomeAssistant
) -> None:
    commands = Commands(hass)
    strip = custom(
        surface,
        env,
        commands,
        lcd={"entity": "media_player.tv", "attribute": "media_title"},
        color={"entity": "light.desk"},
        meter={"entity": "sensor.cpu", "min": 0, "max": 90},
        select={
            "led": {"entity": "media_player.tv"},
            "press": {"service": "media_player.media_play_pause", "entity": "media_player.tv"},
        },
        mute={"led": {"entity": "light.desk"}, "press": {"service": "light.toggle", "entity": "light.desk"}},
    )
    device = surface.strips[0]
    assert device.text == ["Lamp", "Song 2"]
    assert device.color == Color.RED
    assert strip.held_meter("pre_fader") == Lit(round(METER_MAX / 2))
    assert device.leds[Button.SELECT] == Led.ON
    assert device.leds[Button.MUTE] == Led.ON
    strip.on_button(Button.MUTE, True)
    strip.on_button(Button.MUTE, False)
    strip.on_button(Button.SELECT, True)
    await settle()
    assert home.calls == [
        ("light.toggle", {}, "light.desk"),
        ("media_player.media_play_pause", {}, "media_player.tv"),
    ]
    home.set("light.desk", "off")
    home.set("media_player.tv", "paused", media_title="Song 3")
    home.set("sensor.cpu", "unavailable")
    await settle()
    assert device.color == Color.BLACK
    assert device.text == ["Lamp", "Song 3"]
    assert device.leds[Button.SELECT] == Led.OFF
    assert device.leds[Button.MUTE] == Led.OFF
    assert strip.held_meter("pre_fader") is None
    # gone: nothing known, the color stays
    home.disconnect()
    await settle()
    assert device.text == ["Lamp", ""]
    assert device.color == Color.BLACK
    strip.close()
    await commands.wait_closed()


async def test_present_follows_an_entity(surface: RecordingSurface, env: StripEnv, home: FakeHomeAssistant) -> None:
    hass = HomeAssistant(home.connect)
    commands = Commands(hass)
    strip = custom(surface, env, commands, present={"entity": "light.desk"}, color="green")
    told: list[bool | None] = []
    strip.on_presence = lambda: told.append(strip.presence)
    # not connected yet: not known
    assert strip.presence is None
    hass.configure(hass_config())
    await settle()
    assert strip.presence is True
    home.set("light.desk", "unavailable")
    await settle()
    assert strip.presence is False
    assert surface.strips[0].text == ["Lamp", "off"]
    home.set("light.desk", "off")
    await settle()
    # off is there: only unavailable and unknown are not
    assert strip.presence is True
    home.disconnect()
    await settle()
    assert told == [True, False, True, False]
    strip.close()
    await hass.close()


async def test_simulate_reads_entities_but_calls_no_services(
    surface: RecordingSurface, env: StripEnv, home: FakeHomeAssistant, hass: HomeAssistant
) -> None:
    commands = SimulatedCommands(hass)
    strip = custom(
        surface, env, commands, fader={"entity": "light.desk"}, select={"press": {"service": "light.toggle"}}
    )
    value = strip.fader_value()
    assert value is not None
    assert value.value == 51
    strip.on_fader(1.0)
    strip.on_button(Button.SELECT, True)
    await settle()
    assert home.calls == []
    assert value.value == 255
    # a lost connection keeps the value of the simulation
    home.disconnect()
    await settle()
    assert value.value == 255
    strip.close()
    await commands.wait_closed()


async def test_without_a_connection_entities_are_not_known(
    surface: RecordingSurface, env: StripEnv, caplog: pytest.LogCaptureFixture
) -> None:
    commands = Commands()
    strip = custom(
        surface,
        env,
        commands,
        fader={"entity": "light.desk"},
        lcd={"entity": "sensor.x"},
        mute={"press": {"service": "light.toggle"}},
    )
    assert strip.fader_value() is not None
    assert strip.fader_value().value is None  # type: ignore[union-attr]
    assert surface.strips[0].text == ["Lamp", ""]
    strip.on_button(Button.MUTE, True)
    strip.on_fader(0.5)
    await settle()
    assert "Lamp.mute: light.toggle: no connection to Home Assistant" in caplog.text
    assert "Lamp.fader: light.turn_on on light.desk: no connection to Home Assistant" in caplog.text
    strip.close()
    await commands.wait_closed()
    # Simulate without Home Assistant: a value in the middle, as for programs
    simulated = custom(surface, env, SimulatedCommands(), fader={"entity": "light.desk"})
    assert simulated.fader_value().value == 127.5  # type: ignore[union-attr]
    simulated.close()


# -- audio strips ---------------------------------------------------------------------------------------------------


def audio_strip(surface: RecordingSurface, env: StripEnv, options: str) -> VolumeStrip:
    (config,) = strips_of(f'[channel.it]\ntype = "output"\ndevice = "speaker"\nlabel = "It"\n{options}')
    controller = build(config, surface.strips[0], env, {}, "it")
    assert isinstance(controller, VolumeStrip)
    return controller


async def test_an_audio_strip_shows_entities_and_calls_services(
    surface: RecordingSurface, backend: FakeBackend, home: FakeHomeAssistant, hass: HomeAssistant
) -> None:
    commands = Commands(hass)
    env = StripEnv(backend, BehaviorConfig(max_volume=100, encoder_step=5), commands=commands)
    strip = audio_strip(
        surface,
        env,
        'meter = { entity = "sensor.cpu" }\ncolor = { entity = "light.desk" }\nlcd = { entity = "sensor.cpu" }\n'
        'select = { press = { service = "light.toggle", entity = "light.desk" }, led = { entity = "light.desk" } }',
    )
    strip.update(SPEAKER)
    await settle()
    device = surface.strips[0]
    assert device.text == ["It", "45%"]
    assert device.color == Color.RED
    assert strip.held_meter("pre_fader") == Lit(round(0.45 * METER_MAX))
    assert device.leds[Button.SELECT] == Led.ON
    strip.on_button(Button.SELECT, True)
    strip.on_button(Button.SELECT, False)
    await settle()
    assert home.calls == [("light.toggle", {}, "light.desk")]
    home.set("light.desk", "on", brightness=51, rgb_color=[0, 0, 255])
    await settle()
    assert device.color == Color.BLUE
    # another look with the same entities keeps their lines
    lines = dict(strip.bound.lines)
    strip.set_look(dataclasses.replace(strip.look, label="Other"))
    assert strip.bound.lines == lines
    assert all(isinstance(line, EntityLine) for line in lines.values())
    strip.close()
    await commands.wait_closed()


async def test_an_audio_fader_bound_to_an_entity_gives_the_volume_to_the_encoder(
    surface: RecordingSurface, backend: FakeBackend, home: FakeHomeAssistant, hass: HomeAssistant
) -> None:
    commands = Commands(hass)
    env = StripEnv(backend, BehaviorConfig(max_volume=100, encoder_step=5), commands=commands)
    strip = audio_strip(surface, env, 'fader = { entity = "media_player.tv", format = "{value:.0%}" }')
    strip.update(SPEAKER)
    await settle()
    device = surface.strips[0]
    assert device.fader == protocol.fader_value(0.5)
    strip.on_touch(True)
    strip.on_fader(0.8)
    await settle()
    assert home.calls == [("media_player.volume_set", {"volume_level": 0.8}, "media_player.tv")]
    assert device.text[1] == "80%"
    strip.on_touch(False)
    await asyncio.sleep(NOTICE_TIME)
    strip.on_encoder(2)
    await settle()
    assert backend.calls[-1] == ("set_device_volume", strip.direction, "speaker", 60)  # type: ignore[attr-defined]
    assert strip.value_for_run() == 0.8
    strip.close()
    await commands.wait_closed()


async def test_an_entity_it_does_not_have_is_a_warning(
    surface: RecordingSurface, env: StripEnv, hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        strip = custom(surface, env, Commands(hass), lcd={"entity": "sensor.gone"})
    assert "Home Assistant has no entity sensor.gone" in caplog.text
    assert surface.strips[0].text == ["Lamp", ""]
    strip.close()
