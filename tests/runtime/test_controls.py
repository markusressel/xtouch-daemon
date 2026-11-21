"""
The controls of the slots (`[controls]`): they claim controls of the strip of their slot while their `when` holds,
show what they claim, launch, pick modes, toggle states, and put a fader, an encoder and buttons into Home Assistant.
"""

import asyncio
from collections.abc import Callable

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
from xtouch_daemon.config.bindings import ValueBinding
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Led, RingMode
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.controls import Controls, SlotClaim
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.slots.states import Override
from xtouch_daemon.strips import homeassistant as homeassistant_module
from xtouch_daemon.strips.custom import CustomStrip
from xtouch_daemon.strips.knobs import VolumeKnob
from xtouch_daemon.strips.value import CommandValue
from xtouch_daemon.system.commands import SimulatedCommands

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
type = "custom"
label = "Screen"
fader = { set = "brightness -d DP-1 -b {value}", watch = "brightness -d DP-1 --watch", min = 0.1, max = 1.0 }

[controls]
1 = { encoder = { channel = "screen" } }
3 = { fader = { channel = "screen" }, when = "not gaming" }
"""


async def test_a_fader_and_an_encoder_set_a_custom_channel_whatever_the_slot_shows(surface: RecordingSurface) -> None:
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
    # the channel has no encoder of its own: the claim's encoder sets the fader's value in fine steps
    surface.on_event(protocol.EncoderTurned(0, -5))
    await settle()
    assert commands.runs == [["brightness", "-d", "DP-1", "-b", "0.505"]]
    # under the finger, the motor waits; let go, it stays where the hand left it
    surface.on_event(protocol.FaderTouched(2, True))
    surface.on_event(protocol.FaderMoved(2, protocol.fader_value(0.25)))
    await settle()
    assert commands.runs[-1] == ["brightness", "-d", "DP-1", "-b", "0.325"]
    surface.on_event(protocol.FaderTouched(2, False))
    assert surface.strips[2].fader == protocol.fader_value(0.25)
    assert surface.strips[0].ring == (3, RingMode.WRAP)
    rig.mixer.close()
    await commands.wait_closed()


OWN = """
[controls]
1 = { encoder = { set = "brightness -b {value}", max = 1, step = 0.1, push = 1 }, select = { run = "lamp {value}" } }
2 = { select = { run = "lamp off" } }
"""


async def test_controls_set_values_and_run_programs_of_their_own(
    surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + OWN), commands=commands)
    rig.step(STATE)
    await settle()
    # nothing known yet, so the ring is dark; a press has no value for {value}, so nothing runs
    assert surface.strips[0].ring == (0, RingMode.DOT)
    surface.on_event(protocol.ButtonPressed(0, protocol.Button.SELECT, True))
    await settle()
    assert commands.runs == []
    assert "controls.1.select: no value yet for {value}, so lamp does not run" in caplog.text
    surface.on_event(protocol.EncoderPressed(0, True))
    await settle()
    surface.on_event(protocol.EncoderTurned(0, -2))
    await settle()
    assert commands.runs == [["brightness", "-b", "1"], ["brightness", "-b", "0.8"]]
    surface.on_event(protocol.ButtonPressed(0, protocol.Button.SELECT, True))
    surface.on_event(protocol.ButtonPressed(1, protocol.Button.SELECT, True))
    await settle()
    assert commands.runs[-2:] == [["lamp", "0.8"], ["lamp", "off"]]
    assert surface.strips[0].leds[protocol.Button.SELECT] == protocol.Led.OFF
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
            "controls.2.encoder.channel: out is of type output; only custom channels have a value",
        ),
        (
            '[channel.screen]\ntype = "custom"\n[controls]\n2 = { fader = { channel = "screen" } }\n',
            "controls.2.fader.channel: screen has no value for the fader: its fader is not bound to a program",
        ),
        (
            '[channel.screen]\ntype = "custom"\nlcd = { watch = "x" }\n'
            '[controls]\n2 = { encoder = { channel = "screen" } }\n',
            "controls.2.encoder.channel: screen has no value for the encoder: neither its fader nor its encoder",
        ),
        ('[controls]\n2 = { encoder = { program = "x" } }\n', "controls.2.encoder.set: Field required"),
        ('[controls]\n2 = { encoder = { program = "x" } }\n', "controls.2.encoder.program: Extra inputs"),
        ('[controls]\n2 = { encoder = "commands" }\n', "controls.2.encoder: Input should be 'homeassistant'"),
        (
            '[controls]\n2 = { fader = { set = "b {value}", push = 3 } }\n',
            "controls.2: fader.push: a fader has no push, only the encoder",
        ),
        (
            '[controls]\n2 = { select = { run = "b {target}" } }\n',
            "controls.2: select.run: {target} is for custom channels with targets",
        ),
        ("[controls]\n2 = { select = { run = [] } }\n", "controls.2.select.run: an empty command"),
        (
            '[channel.screen]\ntype = "custom"\nfader = { set = "brightness" }\n',
            "channel.screen: fader.set: no argument has {value}, so the value goes nowhere",
        ),
    ],
)
def test_a_custom_channel_and_its_claims_are_checked(text: str, problem: str) -> None:
    with pytest.raises(ConfigError) as error:
        parse_config(BASE + text)
    assert problem in str(error.value)


async def test_a_claim_follows_the_values_of_a_channel_that_switched(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + COMMANDS), commands=commands)
    rig.step(STATE)
    await settle()
    screen = rig.mixer.channels["screen"]
    assert isinstance(screen, CustomStrip)
    before = screen.fader_value()
    assert before is not None
    # another target: other values, which the claims set and show from now on
    other = CommandValue(ValueBinding.model_validate({"set": "other {value}", "max": 10}), commands, 1, "other")
    screen._fader = other  # pyright: ignore[reportPrivateUsage]
    for listener in list(screen.listeners):
        listener()
    other.set(5)
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    surface.on_event(protocol.EncoderTurned(0, 1))
    await settle()
    assert commands.runs[-1] == ["other", "5.1"]
    # the old value is not followed any more
    before.set(1.0)
    assert surface.strips[2].fader == protocol.fader_value(0.51)
    rig.mixer.close()
    # the strip closes the values it has; the old one is the test's now
    before.close()
    await commands.wait_closed()


def _claims_listen(listeners: list[Callable[[], None]]) -> bool:
    return any(isinstance(getattr(listener, "__self__", None), SlotClaim) for listener in listeners)


async def test_a_claim_lets_go_of_the_channel_when_the_controls_close(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + COMMANDS), commands=commands)
    rig.step(STATE)
    screen = rig.mixer.channels["screen"]
    assert isinstance(screen, CustomStrip)
    value = screen.fader_value()
    assert value is not None
    assert _claims_listen(screen.listeners)
    assert _claims_listen(value.listeners)
    # a finger on slot 3's fader when the configuration goes: the desk lets go of it, the value follows its watch again
    surface.on_event(protocol.FaderTouched(2, True))
    assert value.touched
    rig.mixer.controls.close()
    assert not _claims_listen(screen.listeners)
    assert not _claims_listen(value.listeners)
    assert not value.touched
    rig.mixer.close()
    await commands.wait_closed()


async def test_a_finger_on_the_fader_goes_over_to_the_value_of_a_switched_channel(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + COMMANDS), commands=commands)
    rig.step(STATE)
    screen = rig.mixer.channels["screen"]
    assert isinstance(screen, CustomStrip)
    before = screen.fader_value()
    assert before is not None
    surface.on_event(protocol.FaderTouched(2, True))
    other = CommandValue(ValueBinding.model_validate({"set": "other {value}", "max": 10}), commands, 1, "other")
    screen._fader = other  # pyright: ignore[reportPrivateUsage]
    for listener in list(screen.listeners):
        listener()
    # the hand moves the new value; the motor waits for it
    assert (before.touched, other.touched) == (False, True)
    # the same values again: nothing changes
    for listener in list(screen.listeners):
        listener()
    assert sum(isinstance(getattr(listener, "__self__", None), SlotClaim) for listener in other.listeners) == 2
    other.set(5)
    assert surface.strips[2].fader is None
    surface.on_event(protocol.FaderTouched(2, False))
    assert not other.touched
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    rig.mixer.close()
    before.close()
    other.close()
    await commands.wait_closed()


async def test_a_claim_on_a_channel_without_a_value_does_nothing(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + COMMANDS), commands=commands)
    rig.step(STATE)
    screen = rig.mixer.channels["screen"]
    assert isinstance(screen, CustomStrip)
    before = screen.fader_value()
    assert before is not None
    surface.on_event(protocol.FaderTouched(2, True))
    screen._fader = None  # pyright: ignore[reportPrivateUsage]
    for listener in list(screen.listeners):
        listener()
    assert not before.touched
    surface.on_event(protocol.FaderMoved(2, protocol.fader_value(0.25)))
    surface.on_event(protocol.FaderTouched(2, False))
    surface.on_event(protocol.EncoderTurned(0, 1))
    surface.on_event(protocol.EncoderPressed(0, True))
    await settle()
    assert commands.runs == []
    rig.mixer.close()
    before.close()
    await commands.wait_closed()


FADER = """
[controls]
[controls.3]
fader = { set = "brightness -b {value}", watch = "brightness --watch", min = 0.1, max = 1 }
solo = { run = "lamp {value}" }
"""


async def test_a_fader_of_the_controls_with_a_value_of_its_own(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + FADER), commands=commands)
    rig.step(STATE)
    await settle()
    claim = rig.desk.claims[2]
    assert claim is not None
    assert claim.taken == frozenset({"fader", "solo"})
    assert commands.watches == [["brightness", "--watch"]]
    # the fader follows the watch
    commands.print("0.55")
    await settle()
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    # under a finger, the watch waits for the hand
    surface.on_event(protocol.FaderTouched(2, True))
    surface.on_event(protocol.FaderMoved(2, protocol.fader_value(1.0)))
    await settle()
    assert commands.runs == [["brightness", "-b", "1"]]
    commands.print("0.3")
    await settle()
    own = rig.mixer.controls.active[3]
    assert own is not None
    assert own.command_fader is not None
    assert own.command_fader.value == 1
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    # let go, the motor puts it where the hand left it
    surface.on_event(protocol.FaderTouched(2, False))
    assert surface.strips[2].fader == protocol.fader_value(1.0)
    # Solo runs with the fader's value
    press(surface, 2, Button.SOLO)
    await settle()
    assert commands.runs[-1] == ["lamp", "1"]
    assert surface.strips[2].leds[Button.SOLO] == Led.OFF
    # the watch ends with the configuration
    rig.mixer.close()
    await commands.wait_closed()
    assert commands._tasks == set()  # pyright: ignore[reportPrivateUsage]


async def test_a_simulated_value_of_the_controls_starts_in_the_middle_and_sets_nothing(
    surface: RecordingSurface,
) -> None:
    commands = SimulatedCommands()
    config = parse_config(BASE + '[controls]\n3 = { fader = { set = "brightness -b {value}", min = 0, max = 2 } }\n')
    rig = Rig(surface, config, commands=commands)
    rig.step(STATE)
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    surface.on_event(protocol.FaderMoved(2, protocol.fader_value(0.25)))
    await settle()
    claim = rig.mixer.controls.active[3]
    assert claim is not None
    assert claim.command_fader is not None
    assert claim.command_fader.value == 0.5
    rig.mixer.close()
    await commands.wait_closed()


def test_controls_without_commands_only_simulate(surface: RecordingSurface) -> None:
    config = parse_config(BASE)
    controls = Controls(
        config.slots.scene, Desk(surface), Rig(surface, config).engine, None, FakeLauncher(), frozenset, 5
    )
    assert isinstance(controls.commands, SimulatedCommands)
    controls.close()
