"""
The controls of the slots (`[controls]`): they claim controls of the strip of their slot while their `when` holds,
show what they claim, launch, pick modes, toggle states, and put a fader, an encoder and buttons into Home Assistant.
"""

import asyncio

import pytest

from tests.support.audio import output, stream
from tests.support.commands import FakeCommands
from tests.support.hardware import RecordingSurface
from tests.support.launch import FakeLauncher
from tests.support.mqtt import FakeBroker
from tests.support.slots import Rig
from tests.support.tasks import finish_tasks, settle
from tests.support.waiting import until
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Led, RingMode
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.slots.states import Override
from xtouch_daemon.strips import homeassistant as homeassistant_module
from xtouch_daemon.strips.knobs import VolumeKnob

BASE = """
[voip]
provider = "demo"

[channel.out]
type = "output"
device = "speaker"
label = "Speaker"
encoder = "balance"

[channel.voice]
type = "apps"
match = ["mumble"]
label = "Voice"

[state.call]
processes = ["mumble"]
delay_off = 0

[state.gaming]
mode = true
processes = ["mygame"]
delay_off = 0

[slots]
1 = "out"
2 = ["voice if call", "-"]
3 = "-"
4 = "-"
"""

CONTROLS = """
[controls]
2 = { select = { launch = ["mumble"] }, when = "not call" }
3 = { select = "toggle:call", rec = "toggle:gaming", solo = "mode:gaming" }
4 = [{ select = "cycle_modes", when = "gaming" }, { select = "mode:default" }]
"""

STATE = AudioState(outputs=(output("speaker", 50),), default_output="speaker")


def press(surface: RecordingSurface, strip: int, button: Button) -> None:
    surface.on_event(protocol.ButtonPressed(strip, button, True))
    surface.on_event(protocol.ButtonPressed(strip, button, False))


async def test_a_launch_on_a_slot_while_its_when_holds(surface: RecordingSurface) -> None:
    launcher = FakeLauncher()
    running: set[str] = set()
    rig = Rig(surface, parse_config(BASE + CONTROLS), launcher=launcher, processes=lambda: frozenset(running))
    assert rig.mixer.watches_processes
    rig.step(STATE)
    claim = rig.desk.claims[1]
    assert claim is not None
    assert claim.taken == {"select"}
    assert rig.mixer.controllers[1].taken == {"select"}
    press(surface, 1, Button.SELECT)
    assert launcher.spawned != []
    assert surface.strips[1].leds[Button.SELECT] == Led.FLASH

    # Mumble runs: a call, the voice channel shows, and its Select is its own again
    running.add("mumble")
    rig.mixer.processes = frozenset(running)
    rig.step(
        AudioState(outputs=STATE.outputs, default_output="speaker", streams=(stream(1, "Mumble", "mumble"),)),
        frozenset(running),
    )
    assert rig.labels()[1] == "Voice"
    assert rig.desk.claims[1] is None
    assert rig.mixer.controllers[1].taken == frozenset()
    rig.mixer.close()


async def test_buttons_pick_modes_and_toggle_states(surface: RecordingSurface) -> None:
    rig = Rig(surface, parse_config(BASE + CONTROLS))
    engine = rig.engine
    running: set[str] = set()
    engine.on_request = lambda: rig.step(STATE, frozenset(running))
    rig.step(STATE)
    leds = surface.strips[2].leds
    assert (leds[Button.SELECT], leds[Button.REC], leds[Button.SOLO]) == (Led.OFF, Led.OFF, Led.OFF)
    # the state: on by hand, then back to its sources
    press(surface, 2, Button.SELECT)
    assert engine.choices[0] == {"call": Override.ON}
    assert leds[Button.SELECT] == Led.ON
    press(surface, 2, Button.SELECT)
    assert engine.choices[0] == {}
    assert leds[Button.SELECT] == Led.OFF
    # and off by hand while its sources turn it on
    running.add("mumble")
    rig.step(STATE, frozenset(running))
    press(surface, 2, Button.SELECT)
    assert engine.choices[0] == {"call": Override.OFF}
    press(surface, 2, Button.SELECT)
    running.clear()
    # the mode: picked, then back to the rules
    press(surface, 2, Button.REC)
    assert engine.mode == "gaming"
    assert (leds[Button.REC], leds[Button.SOLO]) == (Led.ON, Led.ON)
    # slot 4 has the controls of gaming now: the next mode
    assert surface.strips[3].leds[Button.SELECT] == Led.ON
    press(surface, 3, Button.SELECT)
    assert engine.mode == "default"
    # under the finger the slot kept its controls; the next step gives it those of default
    assert surface.strips[3].leds[Button.SELECT] == Led.OFF
    rig.step(STATE)
    assert surface.strips[3].leds[Button.SELECT] == Led.ON
    press(surface, 2, Button.SOLO)
    assert engine.mode == "gaming"
    press(surface, 2, Button.REC)
    assert engine.mode == "default"
    assert engine.choices[1] is None
    press(surface, 3, Button.SELECT)
    assert engine.choices[1] == "default"
    # Mute stays with what the slot shows; releases alone do nothing
    surface.on_event(protocol.ButtonPressed(2, Button.MUTE, True))
    surface.on_event(protocol.ButtonPressed(2, Button.SELECT, False))
    rig.mixer.close()


async def test_a_slot_under_a_finger_keeps_its_controls(surface: RecordingSurface) -> None:
    rig = Rig(surface, parse_config(BASE + CONTROLS))
    rig.step(STATE)
    first = rig.desk.claims[3]
    surface.on_event(protocol.EncoderPressed(3, True))
    rig.engine.choose_mode("gaming")
    rig.step(STATE)
    assert rig.desk.claims[3] is first
    surface.on_event(protocol.EncoderPressed(3, False))
    rig.step(STATE)
    assert rig.desk.claims[3] is not first
    rig.mixer.close()


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> MqttBridge:
    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    monkeypatch.setattr(homeassistant_module, "FADER_PUBLISH_INTERVAL", 0.001)
    broker = FakeBroker()
    return MqttBridge(parse_config('[mqtt]\nhost = "broker"\n').mqtt, client_factory=broker.client)  # type: ignore[arg-type]


async def test_a_fader_an_encoder_and_buttons_in_home_assistant(surface: RecordingSurface, bridge: MqttBridge) -> None:
    config = parse_config(
        BASE
        + '[mqtt]\nhost = "broker"\n'
        + '[controls]\n1 = { fader = "homeassistant", select = "homeassistant", id = "desk" }\n'
        + '3 = [{ encoder = "homeassistant", rec = "homeassistant", when = "gaming" }, { solo = "toggle:call" }]\n'
    )
    rig = Rig(surface, config, bridge=bridge)
    ids = sorted(entity.unique_id for entity in rig.mixer.controls.entities)
    assert ids == [
        "xtouch_desk_buttons",
        "xtouch_desk_fader",
        "xtouch_desk_select_led",
        "xtouch_slot_3_buttons",
        "xtouch_slot_3_encoder",
        "xtouch_slot_3_rec_led",
    ]
    rig.step(STATE)
    speaker = rig.mixer.controllers[0]
    # the fader is the claim's: the encoder of the speaker sets the volume
    assert isinstance(speaker.knob, VolumeKnob)  # type: ignore[attr-defined]
    # not connected yet: the fader stays, a move does nothing
    surface.on_event(protocol.FaderTouched(0, True))
    surface.on_event(protocol.FaderMoved(0, protocol.fader_value(0.5)))
    surface.on_event(protocol.FaderTouched(0, False))
    press(surface, 0, Button.SELECT)
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF

    rig.mixer.controls.claims[3][0].on_encoder(1)
    assert surface.strips[2].ring == (0, RingMode.DOT)
    task = asyncio.create_task(rig.mixer.run())
    bridge_task = asyncio.create_task(bridge.run())
    entities = rig.mixer.controls.claims[1][0].entities
    assert entities is not None
    assert entities.fader is not None
    await until(lambda: bridge.ready and entities.fader.state is not None)  # type: ignore[union-attr]
    rig.mixer.refresh()
    surface.on_event(protocol.FaderTouched(0, True))
    surface.on_event(protocol.FaderMoved(0, protocol.fader_value(0.4)))
    await until(lambda: entities.fader.state == "40")  # type: ignore[union-attr]
    surface.on_event(protocol.FaderTouched(0, False))
    press(surface, 0, Button.SELECT)
    await entities.leds[Button.SELECT].set_state("flash")
    await until(lambda: surface.strips[0].leds[Button.SELECT] == Led.FLASH)

    # gaming: slot 3's encoder is in Home Assistant
    rig.engine.choose_mode("gaming")
    rig.step(STATE)
    third = rig.mixer.controls.active[3]
    assert third is not None
    assert third.encoder is not None
    await until(lambda: third.connected)
    surface.on_event(protocol.EncoderTurned(2, 3))
    surface.on_event(protocol.EncoderPressed(2, True))
    surface.on_event(protocol.EncoderPressed(2, False))
    press(surface, 2, Button.REC)
    assert surface.strips[2].ring == (third.encoder.ring()[0], RingMode.WRAP)
    await settle()

    # a press on its way when the controls close
    press(surface, 0, Button.SELECT)
    task.cancel()
    bridge_task.cancel()
    rig.mixer.close()
    await finish_tasks()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('[controls]\n2 = { fader = "homeassistant" }\n', "controls.2: Home Assistant needs an [mqtt] section"),
        (
            '[controls]\n2 = [{ rec = "homeassistant", when = "call" }, { rec = "toggle:call" }]\n',
            "controls.2[0]: Home Assistant needs an [mqtt] section",
        ),
        ('[channel.lamp]\ntype = "homeassistant"\n', "channel.lamp: Home Assistant needs an [mqtt] section"),
    ],
)
def test_home_assistant_needs_mqtt(text: str, problem: str) -> None:
    with pytest.raises(ConfigError) as error:
        parse_config(BASE + text)
    assert problem in str(error.value)


COMMANDS = """
[channel.screen]
type = "command"
label = "Screen"
set = "brightness -d DP-1 -b {value}"
watch = "brightness -d DP-1 --watch"
min = 0.1
max = 1.0
push = 1.0

[controls]
1 = { encoder = { channel = "screen" } }
3 = { fader = { channel = "screen" }, when = "not gaming" }
"""


async def test_a_fader_and_an_encoder_set_a_command_channel_whatever_the_slot_shows(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + COMMANDS), commands=commands)
    rig.step(STATE)
    await settle()
    # slot 1 shows the speaker, whose encoder sets the balance: the claim's encoder sets the screen's value
    assert rig.labels()[0] == "Speaker"
    claim = rig.desk.claims[0]
    assert claim is not None
    assert claim.taken == frozenset({"encoder"})
    # the channel watches, though no slot shows it
    assert commands.watches == [["brightness", "-d", "DP-1", "--watch"]]
    commands.print("0.55")
    await settle()
    assert surface.strips[0].ring == (6, RingMode.WRAP)
    # slot 3's fader follows the same value
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    surface.on_event(protocol.EncoderTurned(0, -5))
    await settle()
    assert commands.runs == [["brightness", "-d", "DP-1", "-b", "0.505"]]
    surface.on_event(protocol.EncoderPressed(0, True))
    surface.on_event(protocol.EncoderPressed(0, False))
    await settle()
    assert commands.runs[-1] == ["brightness", "-d", "DP-1", "-b", "1"]
    assert surface.strips[0].ring == (11, RingMode.WRAP)
    assert surface.strips[2].fader == protocol.fader_value(1.0)
    # under the finger, the motor waits; let go, it stays where the hand left it
    surface.on_event(protocol.FaderTouched(2, True))
    surface.on_event(protocol.FaderMoved(2, protocol.fader_value(0.25)))
    await settle()
    assert commands.runs[-1] == ["brightness", "-d", "DP-1", "-b", "0.325"]
    surface.on_event(protocol.FaderTouched(2, False))
    assert surface.strips[2].fader == protocol.fader_value(0.25)
    rig.mixer.close()
    await commands.wait_closed()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (
            '[controls]\n2 = { fader = { channel = "monitor" } }\n',
            "controls.2.fader.channel: monitor is no channel",
        ),
        (
            '[controls]\n2 = { encoder = { channel = "out" } }\n',
            "controls.2.encoder.channel: out is of type output; only command channels have a value",
        ),
        ('[controls]\n2 = { encoder = { program = "x" } }\n', "controls.2.encoder.channel: Field required"),
        ('[controls]\n2 = { encoder = "commands" }\n', "controls.2.encoder: Input should be 'homeassistant'"),
        (
            '[channel.screen]\ntype = "command"\nset = "brightness"\n',
            "channel.screen: set: no argument has {value}, so the value goes nowhere",
        ),
    ],
)
def test_a_command_channel_and_its_claims_are_checked(text: str, problem: str) -> None:
    with pytest.raises(ConfigError) as error:
        parse_config(BASE + text)
    assert problem in str(error.value)
