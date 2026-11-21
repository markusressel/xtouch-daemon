"""
The controls of the slots (`[controls]`): they claim controls of the strip of their slot while their `when` holds,
show what they claim, launch, pick modes, toggle states, and put a fader, an encoder and buttons into Home Assistant.
"""

import asyncio
from collections.abc import Callable, Sequence

import pytest

from tests.support.audio import output, stream
from tests.support.commands import FakeCommands
from tests.support.hardware import RecordingSurface
from tests.support.launch import FakeLauncher
from tests.support.mqtt import FakeBroker
from tests.support.slots import Rig
from tests.support.tasks import finish_tasks, settle
from tests.support.waiting import until
from tests.support.watches import ProgramCommands
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon.audio.meter import Lit
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.bindings import ValueBinding
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
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
            '[controls]\n2 = { solo = { run = "b {value}" }, fader = "homeassistant" }\n',
            "controls.2: solo.run: {value} needs a fader or an encoder bound to a value",
        ),
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
    targets = """
[channel.screen]
type = "custom"
label = "Screen"
targets = [{ name = "Left", value = "DP-1" }, { name = "Right", value = "DP-2" }]
fader = { set = "brightness -d {target} -b {value}", max = 10, step = 0.1 }

[controls]
3 = { fader = { channel = "screen" }, encoder = { channel = "screen" } }
"""
    rig = Rig(surface, parse_config(BASE + targets), commands=commands)
    rig.step(STATE)
    await settle()
    screen = rig.mixer.channels["screen"]
    assert isinstance(screen, CustomStrip)
    before = screen.fader_value()
    assert before is not None
    # another target: other values, which the claims set and show from now on
    screen.switch()
    other = screen.fader_value()
    assert other is not None
    assert other is not before
    other.set(5)
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    surface.on_event(protocol.EncoderTurned(2, 1))
    await settle()
    assert commands.runs[-1] == ["brightness", "-d", "DP-2", "-b", "5.1"]
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
    # the mixer closes the controls again: that does nothing
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
    screen.current.fader = other
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
    screen.current.fader = None
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


class AskedSimulation(SimulatedCommands):
    """A twin's commands that note what they are asked to run (and, as the twin's, run none of it)."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[list[str]] = []

    async def run(self, argv: Sequence[str]) -> None:
        self.asked.append(list(argv))
        await super().run(argv)


async def test_a_simulated_value_of_the_controls_starts_in_the_middle_and_sets_nothing(
    surface: RecordingSurface,
) -> None:
    commands = AskedSimulation()
    config = parse_config(
        BASE
        + "[controls]\n"
        + '3 = { fader = { set = "brightness -b {value}", min = 0, max = 2 }, solo = { run = "lamp {value}" } }\n'
    )
    rig = Rig(surface, config, commands=commands)
    rig.step(STATE)
    claim = rig.mixer.controls.active[3]
    assert claim is not None
    assert claim.command_fader is not None
    # in the middle of min and max: 1, the fader half way up
    assert claim.command_fader.value == 1
    assert surface.strips[2].fader == protocol.fader_value(0.5)
    surface.on_event(protocol.FaderMoved(2, protocol.fader_value(0.25)))
    press(surface, 2, Button.SOLO)
    await settle()
    assert claim.command_fader.value == 0.5
    # set and run go only to the twin's commands, which run nothing (tests/system/test_commands.py)
    assert commands.asked == [["brightness", "-b", "0.5"], ["lamp", "0.5"]]
    rig.mixer.close()
    await commands.wait_closed()


def test_controls_without_commands_only_simulate(surface: RecordingSurface) -> None:
    config = parse_config(BASE)
    controls = Controls(
        config.slots.scene, Desk(surface), Rig(surface, config).engine, None, FakeLauncher(), frozenset, 5
    )
    assert isinstance(controls.commands, SimulatedCommands)
    controls.close()


BOTH = """
1 = { fader = { set = "own {value}", max = 10 }, encoder = { channel = "screen" }, select = { run = "lamp {value}" } }
"""


async def test_a_claim_lets_go_only_of_the_touch_it_set(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + COMMANDS.replace("1 = {", "2 = {") + BOTH), commands=commands)
    rig.step(STATE)
    screen = rig.mixer.channels["screen"]
    assert isinstance(screen, CustomStrip)
    shared = screen.fader_value()
    assert shared is not None
    claim = rig.mixer.controls.active[1]
    assert claim is not None
    own = claim.command_fader
    assert own is not None
    assert claim.command_encoder is shared
    # another hand holds the channel's value (slot 3's fader); the claim's finger is on its own fader
    surface.on_event(protocol.FaderTouched(2, True))
    surface.on_event(protocol.FaderTouched(0, True))
    assert (own.touched, shared.touched) == (True, True)
    # the channel switches (to the same values): the claim moves only its own finger
    for listener in list(screen.listeners):
        listener()
    assert (own.touched, shared.touched) == (True, True)
    surface.on_event(protocol.FaderTouched(0, False))
    assert (own.touched, shared.touched) == (False, True)
    surface.on_event(protocol.FaderTouched(2, False))
    rig.mixer.close()
    await commands.wait_closed()


async def test_a_run_takes_the_first_value_that_is_known(surface: RecordingSurface) -> None:
    commands = FakeCommands()
    rig = Rig(surface, parse_config(BASE + COMMANDS + BOTH.replace("1 = {", "4 = {")), commands=commands)
    rig.step(STATE)
    await settle()
    claim = rig.mixer.controls.active[4]
    assert claim is not None
    assert claim.command_fader is not None
    # its own fader has no value yet; the channel's, which its encoder sets, has one
    assert claim.command_fader.value is None
    commands.print("0.55")
    await settle()
    press(surface, 3, Button.SELECT)
    await settle()
    assert commands.runs == [["lamp", "0.55"]]
    # once the fader has a value, it is the fader's
    surface.on_event(protocol.FaderMoved(3, protocol.fader_value(0.5)))
    press(surface, 3, Button.SELECT)
    await settle()
    assert commands.runs[-2:] == [["own", "5"], ["lamp", "5"]]
    rig.mixer.close()
    await commands.wait_closed()


async def test_controls_close_once(surface: RecordingSurface, bridge: MqttBridge) -> None:
    config = parse_config(BASE + '[mqtt]\nhost = "broker"\n[controls]\n1 = { fader = "homeassistant" }\n')
    rig = Rig(surface, config, bridge=bridge)
    old = rig.mixer.controls
    old.close()
    # the next configuration watches the same entity; the old controls, closed again, leave it be
    new = Controls(config.slots.scene, Desk(surface), rig.engine, bridge, FakeLauncher(), frozenset, 5)
    old.close()
    assert bridge._watchers  # pyright: ignore[reportPrivateUsage]
    new.close()
    assert not bridge._watchers  # pyright: ignore[reportPrivateUsage]
    rig.mixer.close()


SHOWN = """
[[controls.1]]
meter = { watch = "cpu --watch", max = 50 }
color = { watch = "colors" }
lcd = { watch = "clock" }
rec = { led = { watch = "lamp" } }
when = "not gaming"

[[controls.1]]
color = "blue"
select = { press = "toggle:call", led = "off" }
"""


async def test_a_slot_shows_what_its_controls_watch_while_their_when_holds(surface: RecordingSurface) -> None:
    commands = ProgramCommands()
    rig = Rig(surface, parse_config(BASE + SHOWN), commands=commands)
    rig.step(STATE)
    await settle()
    claim = rig.desk.claims[0]
    assert claim is not None
    # it only shows: the buttons and the fader stay with the speaker
    assert claim.taken == frozenset()
    assert claim.shown == {"meter", "color", "lcd", "rec"}
    assert rig.mixer.controllers[0].taken == frozenset()
    device = surface.strips[0]
    view = rig.mixer.controllers[0].strip
    # before the first lines: white, an empty second line, Rec dark, the meter at rest
    assert (device.color, device.text[1], device.leds[Button.REC]) == (Color.WHITE, "", Led.OFF)
    rig.desk.show_meters()
    assert surface.meters(0) == []
    commands.print_to("cpu --watch", "load: 25")
    commands.print_to("colors", "Red")
    commands.print_to("colors", "nonsense")
    commands.print_to("clock", "12:00")
    commands.print_to("lamp", "flash")
    await settle()
    # a line that is no color keeps the last color
    assert (device.color, device.text, device.leds[Button.REC]) == (Color.RED, ["Speaker", "12:00"], Led.FLASH)
    rig.desk.show_meters()
    assert surface.meters(0) == [round(0.5 * protocol.METER_MAX)]
    # what the speaker shows meanwhile is kept, not shown
    view.set_text(1, "50 %")
    view.set_meter(3)
    view.set_color(Color.CYAN)
    assert (device.color, device.text[1]) == (Color.RED, "12:00")
    assert surface.meters(0) == [round(0.5 * protocol.METER_MAX)]

    # gaming: the second entry; the slot shows its own again but the color, Select is the claim's
    rig.engine.choose_mode("gaming")
    rig.step(STATE)
    claim = rig.desk.claims[0]
    assert claim is not None
    assert (claim.taken, claim.shown) == ({"select"}, {"color", "select"})
    assert (device.color, device.text[1], device.leds[Button.REC]) == (Color.BLUE, view.text[1], view.leds[Button.REC])
    press(surface, 0, Button.SELECT)
    assert rig.engine.choices[0] == {"call": Override.ON}
    assert device.leds[Button.SELECT] == Led.OFF

    # back: the watches ran on, so the slot shows their lines at once
    rig.engine.choose_mode("default")
    rig.step(STATE)
    assert (device.color, device.text[1], device.leds[Button.REC]) == (Color.RED, "12:00", Led.FLASH)
    assert [commands.watching(p) for p in ("cpu --watch", "colors", "clock", "lamp")] == [1, 1, 1, 1]
    rig.mixer.close()
    await commands.wait_closed()
    assert commands._tasks == set()  # pyright: ignore[reportPrivateUsage]


async def test_a_led_claim_leaves_the_press_to_what_the_slot_shows(surface: RecordingSurface) -> None:
    config = parse_config(BASE + '[controls]\n2 = { select = { led = { watch = "lamp" } }, when = "call" }\n')
    commands = ProgramCommands()
    rig = Rig(surface, config, commands=commands)
    voice = AudioState(outputs=STATE.outputs, default_output="speaker", streams=(stream(1, "Mumble", "mumble"),))
    rig.step(voice, frozenset({"mumble"}))
    assert rig.labels()[1] == "Voice"
    claim = rig.desk.claims[1]
    assert claim is not None
    assert (claim.taken, claim.shown) == (frozenset(), {"select"})
    commands.print_to("lamp", "on")
    await settle()
    assert surface.strips[1].leds[Button.SELECT] == Led.ON
    # the press stays the voice channel's
    assert rig.mixer.controllers[1].taken == frozenset()
    rig.mixer.close()
    await commands.wait_closed()


async def test_shown_parts_in_home_assistant(surface: RecordingSurface, bridge: MqttBridge) -> None:
    config = parse_config(
        BASE
        + '[mqtt]\nhost = "broker"\n'
        + '[controls]\n3 = { meter = "homeassistant", color = "homeassistant", lcd = "homeassistant", '
        + 'rec = { led = "homeassistant" }, solo = { press = "homeassistant", led = "off" } }\n'
    )
    rig = Rig(surface, config, bridge=bridge)
    ids = sorted(entity.unique_id for entity in rig.mixer.controls.entities)
    assert ids == [
        "xtouch_slot_3_bottom",
        "xtouch_slot_3_buttons",
        "xtouch_slot_3_color",
        "xtouch_slot_3_meter",
        "xtouch_slot_3_rec_led",
    ]
    rig.step(STATE)
    device = surface.strips[2]
    claim = rig.mixer.controls.active[3]
    assert claim is not None
    # Home Assistant is not there yet
    assert (device.color, device.text[1], device.leds[Button.REC]) == (Color.WHITE, "offline", Led.OFF)
    assert claim.meter_level() is None
    task = asyncio.create_task(rig.mixer.run())
    bridge_task = asyncio.create_task(bridge.run())
    entities = claim.entities
    assert entities is not None
    color, bottom, meter = entities.color, entities.bottom, entities.meter
    assert color is not None
    assert bottom is not None
    assert meter is not None
    await until(lambda: bridge.ready and meter.state is not None)
    await color.set_state("green")
    await bottom.set_state("hello")
    await meter.set_state(50)
    await entities.leds[Button.REC].set_state("on")
    await until(lambda: device.color == Color.GREEN and device.text[1] == "hello")
    await until(lambda: device.leds[Button.REC] == Led.ON)
    assert claim.meter_level() == Lit(7)
    press(surface, 2, Button.SOLO)
    await settle()
    assert device.leds[Button.SOLO] == Led.OFF
    task.cancel()
    bridge_task.cancel()
    rig.mixer.close()
    await finish_tasks()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('2 = { when = "call" }', "controls.2: claims nothing (fader, encoder, select, rec, solo, meter, color, lcd)"),
        ("2 = { select = {} }", "controls.2.select: a button takes press, led or both"),
        ('2 = { rec = { led = "press" } }', 'controls.2.rec: led = "press" shows what the press does, but there'),
        ('2 = { select = { led = "on" } }', "controls.2.select.led: Input should be 'off', 'press' or 'homeassistant'"),
        ('2 = { select = { led = "off", foo = 1 } }', "controls.2.select.foo: Extra inputs are not permitted"),
        ('2 = { rec = { press = "toggle:nope" } }', "controls.2.rec.press: toggle:nope: no state or mode nope"),
        ('2 = { solo = { press = { run = "x {value}" } } }', "controls.2: solo.press.run: {value} needs a fader"),
        ('2 = { meter = { watch = "cpu {value}" } }', "controls.2.meter.watch: {value} is for set and run"),
        ('2 = { meter = { watch = "cpu", min = 5, max = 5 } }', "controls.2.meter.max: 5 is not above min (5)"),
        ("2 = { meter = true }", "controls.2.meter: Input should be 'homeassistant'"),
        ('2 = { color = "pink" }', "controls.2.color: Input should be 'off', 'red'"),
        ('2 = { lcd = { watch = "x {target}" } }', "controls.2: lcd.watch: {target} is for custom channels"),
        ('2 = { rec = { led = { watch = "x {target}" } } }', "controls.2: rec.led.watch: {target} is for custom"),
        ('2 = { lcd = { watch = "x" }, id = "clock" }', "controls.2.id: names Home Assistant entities, but no"),
        ('2 = { meter = "homeassistant" }', "controls.2: Home Assistant needs an [mqtt] section"),
        ('2 = { select = { led = "homeassistant" } }', "controls.2: Home Assistant needs an [mqtt] section"),
    ],
)
def test_shown_parts_of_the_controls_are_checked(text: str, problem: str) -> None:
    with pytest.raises(ConfigError) as error:
        parse_config(BASE + "[controls]\n" + text + "\n")
    assert problem in str(error.value)


def test_the_led_of_a_solo_of_the_chord_can_be_claimed() -> None:
    config = parse_config(BASE + '[controls]\n1 = { solo = { led = { watch = "lamp" } } }\n')
    assert config.slots.scene.controls[1][0].taken == ()
    with pytest.raises(ConfigError, match="the Solo buttons of the chord"):
        parse_config(BASE + '[controls]\n1 = { solo = { press = "toggle:call", led = "off" } }\n')
