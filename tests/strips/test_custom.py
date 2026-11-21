"""
Custom channels: a strip whose parts are bound, here to values that programs of your own set and watch.
"""

import asyncio
import dataclasses
import json

import pytest

from tests.support.audio import FakeBackend
from tests.support.commands import FakeCommands
from tests.support.hardware import RecordingSurface
from tests.support.mqtt import FakeBroker
from tests.support.strips import ID, build
from tests.support.tasks import finish_tasks, settle
from tests.support.waiting import until
from tests.support.watches import ProgramCommands
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon.audio.meter import Lit
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.bindings import Target
from xtouch_daemon.config.buttons import HOLD_TIME
from xtouch_daemon.config.sections import BehaviorConfig, MqttConfig
from xtouch_daemon.config.strips import CustomStripConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import METER_MAX, Button, Color, Led, RingMode
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.strips import custom as custom_module
from xtouch_daemon.strips.base import NOTICE_TIME, StripEnv
from xtouch_daemon.strips.custom import CustomStrip
from xtouch_daemon.system.commands import Commands

SET = ("brightness", "-d", "DP-1", "-b", "{value}")
WATCH = ("brightness", "-d", "DP-1", "--watch")
FADER = {"set": SET, "min": 0.1, "max": 1.0}


def config(**options: object) -> CustomStripConfig:
    return CustomStripConfig.model_validate({"type": "custom"} | options)


def ran(commands: FakeCommands) -> list[str]:
    """The values that `set` ran with."""
    return [argv[-1] for argv in commands.runs]


async def test_the_strip_shows_the_label_the_value_on_the_lcd_the_ring_and_the_fader(
    surface: RecordingSurface, env: StripEnv
) -> None:
    commands = FakeCommands()
    env = dataclasses.replace(env, commands=commands)
    fader = FADER | {"watch": WATCH, "format": "{value:.0%}"}
    strip = build(config(label="Left", fader=fader, color="cyan"), surface.strips[0], env)
    assert isinstance(strip, CustomStrip)
    assert strip.encoder_value() is None
    device = surface.strips[0]
    strip.update(AudioState())
    assert device.text == ["Left", ""]
    # nothing known: the fader stays where it is
    assert device.fader is None
    commands.print("0.55")
    await settle()
    assert device.text[1] == "55%"
    assert device.ring == (6, RingMode.WRAP)
    assert device.fader == protocol.fader_value(0.5)
    assert device.color == protocol.Color.CYAN
    # a hand on the fader: the value follows, the motor stays off until it is let go
    strip.on_touch(True)
    strip.on_fader(1.0)
    await settle()
    assert ran(commands) == ["1"]
    assert device.text[1] == "100%"
    assert device.fader == protocol.fader_value(0.5)
    strip.on_touch(False)
    assert device.fader == protocol.fader_value(1.0)
    # the encoder sets the fader's value in fine steps
    strip.on_encoder(-10)
    await settle()
    assert ran(commands)[-1] == "0.91"
    strip.on_encoder_press(True)
    await settle()
    # no push: nothing
    assert ran(commands)[-1] == "0.91"
    strip.close()
    await commands.wait_closed()


async def test_an_encoder_of_its_own_sets_its_own_value(surface: RecordingSurface, env: StripEnv) -> None:
    commands = FakeCommands()
    env = dataclasses.replace(env, commands=commands)
    encoder = {"set": ["volume", "{value}"], "push": 50, "step": 5}
    strip = build(config(encoder=encoder), surface.strips[0], env)
    assert isinstance(strip, CustomStrip)
    assert strip.fader_value() is None
    device = surface.strips[0]
    strip.update(AudioState())
    # no fader: it stays down, and the LCD shows the encoder's value
    assert device.fader == protocol.fader_value(0.0)
    strip.on_fader(0.7)
    strip.on_touch(True)
    strip.on_encoder_press(True)
    await settle()
    assert commands.runs == [["volume", "50"]]
    strip.on_encoder(1)
    await settle()
    assert commands.runs[-1] == ["volume", "55"]
    assert device.text[1] == "55"
    assert device.ring[1] == RingMode.WRAP
    strip.close()
    await commands.wait_closed()


async def test_a_strip_without_bindings_is_dark_and_named_by_its_channel(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = build(config(), surface.strips[0], dataclasses.replace(env, commands=FakeCommands()))
    strip.update(AudioState())
    strip.on_encoder(3)
    strip.on_encoder_press(True)
    device = surface.strips[0]
    assert device.text == [ID.name, ""]
    assert device.ring == (0, RingMode.DOT)
    strip.close()


async def test_the_first_target_fills_the_programs(surface: RecordingSurface, env: StripEnv) -> None:
    commands = FakeCommands()
    targets = [{"name": "Left", "value": "DP-1"}, {"name": "Right", "value": "DP-2"}]
    fader = {"set": "b -d {target} {value}"}
    strip = build(config(fader=fader, targets=targets), surface.strips[0], dataclasses.replace(env, commands=commands))
    strip.on_fader(0.5)
    await settle()
    assert commands.runs == [["b", "-d", "DP-1", "50"]]
    strip.close()
    await commands.wait_closed()


# -- every part bound ------------------------------------------------------------------------------------------------


class Actions:
    """The modes and states of the slots, recording what the buttons ask of them."""

    def __init__(self) -> None:
        self.mode = "default"
        self.values: dict[str, bool] = {}
        self.calls: list[str] = []

    def value(self, name: str) -> bool:
        return self.values.get(name, False)

    def cycle_modes(self) -> None:
        self.calls.append("cycle")
        self.mode = "gaming" if self.mode == "default" else "default"

    def choose_mode(self, mode: str) -> None:
        self.calls.append(f"mode {mode}")
        self.mode = mode

    def toggle(self, name: str) -> None:
        self.calls.append(f"toggle {name}")
        self.values[name] = not self.value(name)


def custom(env: StripEnv, surface: RecordingSurface, commands: Commands, **options: object) -> CustomStrip:
    strip = build(config(**options), surface.strips[0], dataclasses.replace(env, commands=commands))
    assert isinstance(strip, CustomStrip)
    strip.update(AudioState())
    return strip


def press(strip: CustomStrip, button: Button) -> None:
    strip.on_button(button, True)
    strip.on_button(button, False)


async def test_watches_set_the_lcd_the_color_the_meter_and_the_leds(surface: RecordingSurface, env: StripEnv) -> None:
    commands = ProgramCommands()
    strip = custom(
        env,
        surface,
        commands,
        label="Player",
        lcd={"watch": "title --watch"},
        color={"watch": "color --watch"},
        meter={"watch": "cpu --watch", "min": 0, "max": 50},
        select={"led": {"watch": "playing --watch"}},
        mute={"led": {"watch": "muted --watch"}},
    )
    device = surface.strips[0]
    # nothing printed yet: dark parts, the configured color, no meter
    assert device.text == ["Player", ""]
    assert device.color == Color.WHITE
    assert strip.held_meter("pre_fader") is None
    assert device.leds[Button.SELECT] == Led.OFF
    commands.print_to("title --watch", "Song 2")
    commands.print_to("color --watch", "Magenta")
    commands.print_to("cpu --watch", "25")
    commands.print_to("playing --watch", "yes")
    commands.print_to("muted --watch", "flash")
    await settle()
    assert device.text == ["Player", "Song 2"]
    assert device.color == Color.MAGENTA
    assert strip.held_meter("pre_fader") == Lit(round(METER_MAX / 2))
    assert device.leds[Button.SELECT] == Led.ON
    assert device.leds[Button.MUTE] == Led.FLASH
    # a line that is no color keeps the configured one, any other word turns an LED off
    commands.print_to("color --watch", "plaid")
    commands.print_to("playing --watch", "paused")
    commands.print_to("cpu --watch", "load: 80")
    await settle()
    assert device.color == Color.WHITE
    assert device.leds[Button.SELECT] == Led.OFF
    assert strip.held_meter("post_fader") == Lit(METER_MAX)
    strip.close()
    await commands.wait_closed()


async def test_a_value_set_by_hand_shows_for_a_moment_over_the_lcd_of_a_watch(
    surface: RecordingSurface, env: StripEnv
) -> None:
    commands = ProgramCommands()
    strip = custom(env, surface, commands, fader=FADER | {"format": "{value:.0%}"}, lcd={"watch": "title --watch"})
    commands.print_to("title --watch", "Desk")
    await settle()
    device = surface.strips[0]
    assert device.text[1] == "Desk"
    strip.on_fader(0.5)
    await settle()
    assert device.text[1] == "55%"
    await asyncio.sleep(NOTICE_TIME)
    assert device.text[1] == "Desk"
    strip.on_encoder(1)
    assert device.text[1] == "56%"
    strip.close()
    await commands.wait_closed()


async def test_buttons_run_programs_with_the_value_and_light_while_they_run(
    surface: RecordingSurface, env: StripEnv
) -> None:
    commands = ProgramCommands()
    commands.run_time = 1.0
    strip = custom(
        env,
        surface,
        commands,
        fader=FADER,
        select={"press": {"run": "save {value}"}, "led": "press"},
        rec={"press": {"run": "reset"}, "hold": {"run": "reset --hard"}},
    )
    device = surface.strips[0]
    # no value yet: nothing runs
    press(strip, Button.SELECT)
    await settle()
    assert commands.runs == []
    strip.on_fader(0.5)
    await asyncio.sleep(1)
    press(strip, Button.SELECT)
    await settle()
    assert commands.runs[-1] == ["save", "0.55"]
    assert device.leds[Button.SELECT] == Led.ON
    await asyncio.sleep(1)
    assert device.leds[Button.SELECT] == Led.OFF
    # a press shorter than the hold, then a hold
    press(strip, Button.REC)
    await settle()
    assert commands.runs[-1] == ["reset"]
    strip.on_button(Button.REC, True)
    await asyncio.sleep(HOLD_TIME)
    assert commands.runs[-1] == ["reset", "--hard"]
    strip.on_button(Button.REC, False)
    await settle()
    assert commands.runs[-1] == ["reset", "--hard"]
    # a run that fails is logged, the strip goes on
    commands.failing = "no such display"
    press(strip, Button.REC)
    await asyncio.sleep(1)
    assert device.leds[Button.REC] == Led.OFF
    strip.close()
    await commands.wait_closed()


async def test_buttons_choose_modes_and_states(surface: RecordingSurface, env: StripEnv) -> None:
    actions = Actions()
    strip = custom(
        dataclasses.replace(env, actions=actions),
        surface,
        ProgramCommands(),
        select={"press": "cycle_modes", "led": "press"},
        rec={"press": "mode:night", "led": "press"},
        solo={"press": "toggle:quiet", "led": "press"},
        mute={"press": "off", "led": "press"},
    )
    device = surface.strips[0]
    press(strip, Button.SELECT)
    press(strip, Button.SOLO)
    assert actions.calls == ["cycle", "toggle quiet"]
    assert device.leds[Button.SELECT] == Led.ON
    assert device.leds[Button.SOLO] == Led.ON
    assert device.leds[Button.REC] == Led.OFF
    press(strip, Button.REC)
    assert actions.calls[-1] == "mode night"
    assert device.leds[Button.REC] == Led.ON
    assert device.leds[Button.MUTE] == Led.OFF
    strip.close()


async def test_modes_without_the_slots_do_nothing(surface: RecordingSurface, env: StripEnv) -> None:
    strip = custom(env, surface, ProgramCommands(), select={"press": "cycle_modes", "led": "press"})
    press(strip, Button.SELECT)
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF
    strip.close()


TARGETS = [{"name": "Left", "value": "DP-1"}, {"name": "Right", "value": "DP-2"}]
SCREENS: dict[str, object] = {
    "targets": TARGETS,
    "fader": {"set": "b -d {target} {value}", "watch": "b -d {target} --watch", "min": 0, "max": 10},
    "color": {"watch": "theme --watch"},
    "select": {"press": "next", "led": "press"},
    "rec": {"press": {"run": "reset -d {target}"}},
}


async def test_next_switches_the_target_with_values_and_watches_of_its_own(
    surface: RecordingSurface, env: StripEnv
) -> None:
    commands = ProgramCommands()
    strip = custom(env, surface, commands, label="Screens", **SCREENS)
    switched: list[str] = []
    strip.listeners.append(lambda: switched.append("switched"))
    device = surface.strips[0]
    await settle()
    # every watch runs, a program without {target} once
    assert commands.watching("b -d DP-1 --watch") == 1
    assert commands.watching("b -d DP-2 --watch") == 1
    assert commands.watching("theme --watch") == 1
    commands.print_to("b -d DP-1 --watch", "2")
    commands.print_to("b -d DP-2 --watch", "8")
    await settle()
    assert device.text == ["Screens", "2"]
    left = strip.fader_value()
    press(strip, Button.SELECT)
    assert switched == ["switched"]
    assert strip.target == Target(name="Right", value="DP-2")
    assert strip.fader_value() is not left
    # the name of the new target for a moment, and its value
    assert device.text == ["Screens", "Right"]
    assert device.fader == protocol.fader_value(0.8)
    assert device.leds[Button.SELECT] == Led.ON
    await asyncio.sleep(NOTICE_TIME)
    assert device.text[1] == "8"
    strip.on_fader(0.5)
    press(strip, Button.REC)
    await settle()
    assert commands.runs == [["b", "-d", "DP-2", "5"], ["reset", "-d", "DP-2"]]
    press(strip, Button.SELECT)
    assert strip.target == Target(name="Left", value="DP-1")
    assert device.leds[Button.SELECT] == Led.OFF
    # a hand replaces the name with the value at once
    strip.on_encoder(1)
    assert device.text[1] == "2.1"
    strip.close()
    await commands.wait_closed()


async def test_without_a_label_the_lcd_names_the_target(surface: RecordingSurface, env: StripEnv) -> None:
    commands = ProgramCommands()
    strip = custom(env, surface, commands, **SCREENS)
    assert surface.strips[0].text[0] == "Left"
    strip.switch()
    assert surface.strips[0].text[0] == "Right"
    strip.close()
    await commands.wait_closed()


async def test_together_sets_every_target_and_shows_the_first(surface: RecordingSurface, env: StripEnv) -> None:
    commands = ProgramCommands()
    screens = SCREENS | {"together": True, "select": {"press": {"run": "save -d {target} {value}"}}}
    strip = custom(env, surface, commands, **screens)
    commands.print_to("b -d DP-2 --watch", "9")
    await settle()
    strip.on_fader(0.3)
    await settle()
    assert sorted(commands.runs) == [["b", "-d", "DP-1", "3"], ["b", "-d", "DP-2", "3"]]
    strip.on_encoder(5)
    await settle()
    assert sorted(commands.runs[-2:]) == [["b", "-d", "DP-1", "3.5"], ["b", "-d", "DP-2", "3.5"]]
    press(strip, Button.SELECT)
    await settle()
    assert sorted(commands.runs[-2:]) == [["save", "-d", "DP-1", "3.5"], ["save", "-d", "DP-2", "3.5"]]
    assert surface.strips[0].text == ["Left", "3.5"]
    strip.close()
    await commands.wait_closed()


async def test_present_tells_whether_the_channel_is_there(surface: RecordingSurface, env: StripEnv) -> None:
    commands = ProgramCommands()
    strip = custom(env, surface, commands, present={"watch": "screen-on --watch"})
    told: list[bool | None] = []
    strip.on_presence = lambda: told.append(strip.presence)
    assert strip.presence is None
    commands.print_to("screen-on --watch", "DP-1")
    await settle()
    commands.print_to("screen-on --watch", "DP-1 connected")
    commands.print_to("screen-on --watch", "  ")
    await settle()
    assert told == [True, False]
    strip.close()
    await commands.wait_closed()
    always = custom(env, surface, commands)
    assert always.presence is True
    always.close()


async def test_a_channel_with_targets_is_present_while_one_of_them_is(surface: RecordingSurface, env: StripEnv) -> None:
    commands = ProgramCommands()
    strip = custom(env, surface, commands, **SCREENS, present={"watch": "connected {target}"})
    commands.print_to("connected DP-1", "")
    await settle()
    assert strip.presence is None
    commands.print_to("connected DP-2", "yes")
    await settle()
    assert strip.presence is True
    commands.print_to("connected DP-2", "")
    await settle()
    assert strip.presence is False
    strip.close()
    await commands.wait_closed()


# -- Home Assistant --------------------------------------------------------------------------------------------------

TOPIC = "homeassistant/{component}/xtouch/lights_{part}/{kind}"


def topic(component: str, part: str, kind: str = "state") -> str:
    return TOPIC.format(component=component, part=part, kind=kind)


def published(broker: FakeBroker, state_topic: str) -> list[str]:
    return [payload for t, payload, _ in broker.published if t == state_topic]


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def bridge(broker: FakeBroker, monkeypatch: pytest.MonkeyPatch) -> MqttBridge:
    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    monkeypatch.setattr(custom_module, "FADER_PUBLISH_INTERVAL", 0.005)
    return MqttBridge(MqttConfig(host="broker"), client_factory=broker.client)


async def in_home_assistant(
    surface: RecordingSurface, bridge: MqttBridge, commands: Commands, **options: object
) -> CustomStrip:
    """The strip of the channel `lights`, connected to Home Assistant."""
    env = StripEnv(FakeBackend(), BehaviorConfig(encoder_step=5), bridge, commands=commands)
    strip = build(config(**options), surface.strips[0], env, name="lights")
    assert isinstance(strip, CustomStrip)
    strip.update(AudioState())
    bridge.on_connection = lambda connected: strip.show()
    await bridge.set_entities(strip.entities)
    task = asyncio.create_task(bridge.run())
    await until(lambda: bridge.ready)
    assert not task.done()
    return strip


async def test_parts_in_home_assistant_are_its_entities(
    surface: RecordingSurface, bridge: MqttBridge, broker: FakeBroker
) -> None:
    commands = ProgramCommands()
    strip = await in_home_assistant(
        surface,
        bridge,
        commands,
        label="Lights",
        fader="homeassistant",
        lcd="homeassistant",
        color="homeassistant",
        meter="homeassistant",
        select={"press": "homeassistant", "led": "homeassistant"},
        rec={"led": "homeassistant"},
    )
    device = surface.strips[0]
    events = json.loads(broker.retained[topic("event", "buttons", "config")])
    assert events["event_types"] == ["fader_touched", "fader_released", "select_pressed", "select_released"]
    assert broker.retained[topic("select", "color")] == "white"
    assert broker.retained[topic("select", "rec_led")] == "off"
    assert json.loads(broker.retained[topic("text", "bottom", "config")])["max"] == protocol.LCD_CELL_WIDTH
    assert topic("number", "encoder", "config") not in broker.retained

    broker.publish(topic("number", "fader", "set"), "75")
    broker.publish(topic("text", "bottom", "set"), "Warm")
    broker.publish(topic("select", "color", "set"), "red")
    broker.publish(topic("number", "meter", "set"), "50")
    broker.publish(topic("select", "rec_led", "set"), "flash")
    await until(lambda: device.leds.get(Button.REC) == Led.FLASH)
    await surface.settled()
    assert surface.faders(0)[-1] == protocol.fader_value(0.75)
    assert device.text == ["Lights", "Warm"]
    assert device.color == Color.RED
    assert device.ring == (9, RingMode.WRAP)
    assert strip.held_meter("pre_fader") == Lit(round(METER_MAX / 2))
    assert device.leds[Button.SELECT] == Led.OFF

    # the encoder sets the fader in fine steps, the fader its number; Select and touches are events
    strip.on_encoder(2)
    await until(lambda: published(broker, topic("number", "fader"))[-1:] == ["76"])
    strip.on_touch(True)
    strip.on_fader(0.5)
    strip.on_touch(False)
    await until(lambda: published(broker, topic("number", "fader"))[-1:] == ["50"])
    press(strip, Button.SELECT)
    strip.on_button(Button.SOLO, True)
    await until(lambda: len(published(broker, topic("event", "buttons"))) == 4)
    kinds = [json.loads(payload)["event_type"] for payload in published(broker, topic("event", "buttons"))]
    assert kinds == ["fader_touched", "fader_released", "select_pressed", "select_released"]
    strip.close()
    await finish_tasks()


async def test_values_of_programs_are_numbers_in_home_assistant(
    surface: RecordingSurface, bridge: MqttBridge, broker: FakeBroker
) -> None:
    commands = ProgramCommands()
    fader = {"set": "light {target} {value}", "watch": "light {target} --watch", "min": 0.1, "max": 1.0}
    strip = await in_home_assistant(
        surface,
        bridge,
        commands,
        fader=fader,
        encoder="homeassistant",
        targets=TARGETS,
        select={"press": "next"},
    )
    number = json.loads(broker.retained[topic("number", "fader", "config")])
    assert (number["min"], number["max"], number["step"]) == (0.1, 1.0, 0.001)
    commands.print_to("light DP-1 --watch", "0.4")
    commands.print_to("light DP-2 --watch", "0.9")
    await until(lambda: published(broker, topic("number", "fader"))[-1:] == ["0.4"])
    # Home Assistant sets the value of the target the strip controls
    broker.publish(topic("number", "fader", "set"), "0.6")
    await until(lambda: commands.runs == [["light", "DP-1", "0.6"]])
    press(strip, Button.SELECT)
    await until(lambda: published(broker, topic("number", "fader"))[-1:] == ["0.9"])
    broker.publish(topic("number", "fader", "set"), "0.2")
    await until(lambda: commands.runs[-1:] == [["light", "DP-2", "0.2"]])
    # the encoder is a number of its own
    broker.publish(topic("number", "encoder", "set"), "40")
    await until(lambda: surface.strips[0].ring == (5, RingMode.WRAP))
    strip.on_encoder(1)
    await until(lambda: published(broker, topic("number", "encoder"))[-1:] == ["45"])
    strip.on_encoder_press(True)
    await until(lambda: len(published(broker, topic("event", "buttons"))) == 1)
    strip.close()
    await finish_tasks()


async def test_without_mqtt_parts_in_home_assistant_stay_dark(surface: RecordingSurface, env: StripEnv) -> None:
    strip = custom(
        env,
        surface,
        ProgramCommands(),
        fader="homeassistant",
        lcd="homeassistant",
        color="homeassistant",
        meter="homeassistant",
        select={"press": "homeassistant", "led": "homeassistant"},
    )
    press(strip, Button.SELECT)
    strip.on_fader(0.4)
    strip.on_encoder(1)
    assert surface.strips[0].text[1] == ""
    assert strip.held_meter("pre_fader") is None
    assert strip.entities == {}
    strip.close()


async def test_a_value_known_before_home_assistant_is_there_is_published_once_it_is(
    surface: RecordingSurface, bridge: MqttBridge, broker: FakeBroker, caplog: pytest.LogCaptureFixture
) -> None:
    commands = ProgramCommands()
    env = StripEnv(FakeBackend(), BehaviorConfig(encoder_step=5), bridge, commands=commands)
    fader = {"set": "light {value}", "watch": "light --watch", "min": 0.1, "max": 1.0}
    strip = build(config(fader=fader), surface.strips[0], env, name="lights")
    assert isinstance(strip, CustomStrip)
    strip.update(AudioState())
    # the program prints its value before the broker is there
    commands.print_to("light --watch", "0.4")
    await until(lambda: surface.strips[0].text[1] == "0.4")
    await bridge.set_entities(strip.entities)
    task = asyncio.create_task(bridge.run())
    await until(lambda: published(broker, topic("number", "fader"))[-1:] == ["0.4"])
    # a command that is not a number is a warning, nothing runs
    broker.publish(topic("number", "fader", "set"), "bright")
    await until(lambda: "Home Assistant sent 'bright', not a number" in caplog.text)
    assert commands.runs == []
    assert not task.done()
    strip.close()
    await finish_tasks()


async def test_a_run_that_ends_after_the_strip_closed_shows_nothing(surface: RecordingSurface, env: StripEnv) -> None:
    commands = ProgramCommands()
    commands.run_time = 1.0
    strip = custom(env, surface, commands, select={"press": {"run": "save"}, "led": "press"})
    device = surface.strips[0]
    press(strip, Button.SELECT)
    await settle()
    assert device.leds[Button.SELECT] == Led.ON
    strip.close()
    await asyncio.sleep(1)
    assert commands.runs == [["save"]]
    # the old strip wrote nothing: the strip is another one's now
    assert device.leds[Button.SELECT] == Led.ON
    await commands.wait_closed()
