"""
`xtouch-daemon test`: lights up everything on the device and moves the faders (the sweep), then every strip answers
its own controls (the `TestBench`), so each output of the device and each of its values can be shown by hand. See
docs/development/design/interactive-test.md.
"""

import asyncio
import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import assert_never

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.hardware.surface import Surface

STEP = 0.08
INPUT_SECONDS = 2.0
"""How long the LCD shows the last input on its strip before it shows what the encoder edits again."""
METER_REFRESH = 0.1
"""How often the meters of raised faders are sent again (as the daemon does): the device lets a meter fall by itself."""
FADER_STEPS = 10
"""The motor moves the fader in steps of 1/FADER_STEPS (0 %, 10 %, ... 100 %)."""

LED_STEPS = (Led.OFF, Led.ON, Led.FLASH)
"""The states a button's LED goes through, one a press."""
LED_NAMES = {Led.OFF: "off", Led.ON: "on", Led.FLASH: "fl"}
MODE_NAMES = {RingMode.DOT: "dot", RingMode.BOOST_CUT: "boost", RingMode.WRAP: "wrap", RingMode.SPREAD: "spread"}
CENTER_MODE_NAMES = {
    RingMode.DOT: "dot+c",
    RingMode.BOOST_CUT: "boost+c",
    RingMode.WRAP: "wrap+c",
    RingMode.SPREAD: "sprd+c",
}
"""The modes with the LED below the ring lit (7 characters at most, the width of an LCD)."""
RING_START = (protocol.RING_MAX + 1) // 2
"""The position of the ring at the start: the middle, so each mode shows how it lights it."""


class Target(enum.Enum):
    """What the encoder of a strip edits; a push goes to the next one."""

    RING = "ring"
    MODE = "mode"
    COLOR = "color"
    FADER = "fader"


def describe(event: protocol.StripEvent) -> str:
    strip = f"strip {event.strip + 1}"
    match event:
        case protocol.FaderMoved(value=value):
            return f"{strip}: fader at {protocol.fader_fraction(value):.0%}"
        case protocol.FaderTouched(touched=touched):
            return f"{strip}: fader {'touched' if touched else 'released'}"
        case protocol.ButtonPressed(button=button, pressed=pressed):
            return f"{strip}: {button.name.lower()} {'pressed' if pressed else 'released'}"
        case protocol.EncoderTurned(steps=steps):
            return f"{strip}: encoder {steps:+d}"
        case protocol.EncoderPressed(pressed=pressed):
            return f"{strip}: encoder {'pressed' if pressed else 'released'}"
        case _ as unreachable:
            assert_never(unreachable)


@dataclass
class StripTest:
    """What the test shows on one strip."""

    color: Color
    target: Target = Target.RING
    ring: int = RING_START
    """0 (dark) or 1..RING_MAX."""
    mode: int = 0
    """0..7: the 4 modes of the ring (`RingMode`), each without and with the LED below the ring."""
    fader: int = 0
    """0..FADER_STEPS: where the encoder put the fader."""
    meter: int = 0
    """The level of the meter (0..METER_MAX), which follows the fader."""
    leds: dict[Button, Led] = field(default_factory=lambda: dict.fromkeys(Button, Led.OFF))
    timer: asyncio.TimerHandle | None = None
    """Ends the text of the last input on the LCD (see INPUT_SECONDS)."""

    @property
    def ring_mode(self) -> RingMode:
        return RingMode(self.mode // 2)

    @property
    def center(self) -> bool:
        return self.mode % 2 == 1

    def value(self) -> str:
        """What the encoder edits, and its value, as the LCD shows it."""
        match self.target:
            case Target.RING:
                return f"ring {self.ring}"
            case Target.MODE:
                return (CENTER_MODE_NAMES if self.center else MODE_NAMES)[self.ring_mode]
            case Target.COLOR:
                return self.color.name.lower()
            case Target.FADER:
                return f"fad {self.fader * 100 // FADER_STEPS}%"


class TestBench:
    """
    Every strip answers its own controls. Fader: the meter follows it. Touch: the LCD says so. Rec, Solo, Mute,
    Select: their LED goes on, flashing, off. Encoder turned: steps what it edits; pushed: the next thing to edit (the
    position of the ring, its mode, the color of the LCD, the motor fader). `echo` gets each input with the answer of
    its strip.
    """

    __test__ = False
    """Not a test class of pytest, despite its name."""

    def __init__(self, strips: Sequence[Strip], echo: Callable[[str], None]):
        """`strips`: those of the device (`Surface.strips`), or those it lends a test (`Surface.lend()`)."""
        self.strips = strips
        self.echo = echo
        self.tests = [StripTest(Color(index % 7 + 1)) for index in range(protocol.STRIPS)]
        self._meters: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Shows the start on every strip, and keeps the meters of raised faders up from now on."""
        for strip, test in zip(self.strips, self.tests, strict=True):
            strip.set_color(test.color)
            for button in Button:
                strip.set_led(button, test.leds[button])
            strip.set_ring(test.ring, test.ring_mode, test.center)
            strip.set_fader(test.fader / FADER_STEPS)
            strip.set_text(0, f"strip {strip.index + 1}")
            strip.set_text(1, test.value())
        self._meters = asyncio.create_task(self._keep_meters(), name="test meters")

    def close(self) -> None:
        """Ends the timers and the meters; what the strips show stays."""
        for test in self.tests:
            timer, test.timer = test.timer, None
            if timer is not None:
                timer.cancel()
        meters, self._meters = self._meters, None
        if meters is not None:
            meters.cancel()

    def handle(self, event: protocol.StripEvent) -> None:
        """An input on the device (or a hand on its drawing): its strip answers."""
        strip = self.strips[event.strip]
        test = self.tests[event.strip]
        answer = self._answer(strip, test, event)
        if answer is None:
            self.echo(describe(event))
            return
        self._show(strip, test, answer)
        self.echo(f"{describe(event)}: {answer}")

    def _answer(self, strip: Strip, test: StripTest, event: protocol.StripEvent) -> str | None:
        """Shows the answer of the strip to the input, and returns its text for the LCD (None: no answer)."""
        match event:
            case protocol.FaderMoved(value=value):
                fraction = protocol.fader_fraction(value)
                # touched, the motor stays still; let go, the fader stays where the hand left it
                strip.set_fader(fraction)
                self._set_meter(strip, test, fraction)
                return f"fad {fraction:.0%}"
            case protocol.FaderTouched(touched=touched):
                return "touch" if touched else "let go"
            case protocol.ButtonPressed(button=button, pressed=True):
                state = LED_STEPS[(LED_STEPS.index(test.leds[button]) + 1) % len(LED_STEPS)]
                test.leds[button] = state
                strip.set_led(button, state)
                return f"{button.name.lower()} {LED_NAMES[state]}"
            case protocol.EncoderTurned(steps=steps):
                self._turn(strip, test, steps)
                return test.value()
            case protocol.EncoderPressed(pressed=True):
                targets = list(Target)
                test.target = targets[(targets.index(test.target) + 1) % len(targets)]
                return f"> {test.target.value}"
            case protocol.ButtonPressed() | protocol.EncoderPressed():
                # let go
                return None
            case _ as unreachable:
                assert_never(unreachable)

    def _turn(self, strip: Strip, test: StripTest, steps: int) -> None:
        match test.target:
            case Target.RING:
                test.ring = (test.ring + steps) % (protocol.RING_MAX + 1)
                strip.set_ring(test.ring, test.ring_mode, test.center)
            case Target.MODE:
                test.mode = (test.mode + steps) % (len(RingMode) * 2)
                strip.set_ring(test.ring, test.ring_mode, test.center)
            case Target.COLOR:
                test.color = Color((test.color + steps) % len(Color))
                strip.set_color(test.color)
            case Target.FADER:
                test.fader = (test.fader + steps) % (FADER_STEPS + 1)
                fraction = test.fader / FADER_STEPS
                strip.set_fader(fraction)
                self._set_meter(strip, test, fraction)

    def _set_meter(self, strip: Strip, test: StripTest, fraction: float) -> None:
        test.meter = round(fraction * protocol.METER_MAX)
        strip.set_meter(test.meter)

    def _show(self, strip: Strip, test: StripTest, text: str) -> None:
        """The text of an input on the bottom line of the LCD, for INPUT_SECONDS; then what the encoder edits."""
        # the handle is replaced before anything else happens: a timer of an earlier input never ends a later one
        timer, test.timer = test.timer, None
        if timer is not None:
            timer.cancel()
        strip.set_text(1, text)
        test.timer = asyncio.get_running_loop().call_later(INPUT_SECONDS, self._input_shown, strip, test)

    def _input_shown(self, strip: Strip, test: StripTest) -> None:
        test.timer = None
        strip.set_text(1, test.value())

    async def _keep_meters(self) -> None:
        while True:
            for strip, test in zip(self.strips, self.tests, strict=True):
                if test.meter > 0:
                    strip.set_meter(test.meter)
            await asyncio.sleep(METER_REFRESH)


async def sweep(surface: Surface, step: float = STEP, strips: Sequence[Strip] | None = None) -> None:
    """
    Every strip lights its LCD in a color, its LEDs, ring and meter, and moves its fader; then it is dark again.
    `strips`: those the surface lent the test (`Surface.lend()`), by default its own.
    """
    strips = strips if strips is not None else surface.strips
    for strip in strips:
        strip.set_color(Color(strip.index % 7 + 1))
        strip.set_text(0, "X-Touch")
        strip.set_text(1, f"strip {strip.index + 1}")
        for button in Button:
            strip.set_led(button, Led.ON)
    for position in range(1, protocol.RING_MAX + 1):
        for strip in strips:
            strip.set_ring(position, RingMode.DOT)
            strip.set_meter(round(position / protocol.RING_MAX * protocol.METER_MAX))
        await asyncio.sleep(step)
    for fraction in (1.0, 0.0):
        for strip in strips:
            strip.set_fader(fraction)
        await surface.settled()
        await asyncio.sleep(step * 4)
    for strip in strips:
        strip.reset()
    await surface.settled()


async def run_selftest(
    device_name: str,
    echo: Callable[[str], None],
    show_events: bool = True,
    surface: Surface | None = None,
    step: float = STEP,
) -> None:
    surface = surface or Surface(device_name)
    surface.open()
    echo(f"Connected to {device_name}. Testing the LCDs, LEDs, rings, meters and faders...")
    bench: TestBench | None = None
    try:
        await sweep(surface, step)
        echo("Done: every strip lit its LCD in a color, its LEDs, ring and meter, and moved its fader.")
        if show_events:
            echo(
                "Now every strip answers its controls. Fader: the meter follows. Rec, Solo, Mute, Select: the LED goes"
                " on, flashing, off. Encoder: turn to change, push for the next of ring, mode, color, fader. Ctrl+C"
                " stops."
            )
            bench = TestBench(surface.strips, echo)
            bench.start()
            surface.on_event = bench.handle
            surface.on_unknown = lambda message: echo(f"unknown message: {message.hex(' ')}")
            await asyncio.Event().wait()
    finally:
        if bench is not None:
            bench.close()
        for strip in surface.strips:
            strip.reset()
        await surface.settled()
        await surface.close()
