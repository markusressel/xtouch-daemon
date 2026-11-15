"""`xtouch-daemon test`: lights up everything on the device and moves the faders, then shows what happens on it."""

import asyncio
from collections.abc import Callable
from typing import assert_never

from xtouch_daemon import protocol
from xtouch_daemon.protocol import Button, Color, Led, RingMode
from xtouch_daemon.surface import Surface

STEP = 0.08


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
    try:
        for strip in surface.strips:
            strip.set_color(Color(strip.index % 7 + 1))
            strip.set_text(0, "X-Touch")
            strip.set_text(1, f"strip {strip.index + 1}")
            for button in Button:
                strip.set_led(button, Led.ON)
        for position in range(1, protocol.RING_MAX + 1):
            for strip in surface.strips:
                strip.set_ring(position, RingMode.DOT)
                strip.set_meter(round(position / protocol.RING_MAX * protocol.METER_MAX))
            await asyncio.sleep(step)
        for fraction in (1.0, 0.0):
            for strip in surface.strips:
                strip.set_fader(fraction)
            await surface.settled()
            await asyncio.sleep(step * 4)
        for strip in surface.strips:
            strip.reset()
        await surface.settled()
        echo("Done: every strip lit its LCD in a color, its LEDs, ring and meter, and moved its fader.")
        if show_events:
            echo("Now use the device: faders, buttons and encoders show up here. Ctrl+C stops.")
            surface.on_event = lambda event: echo(describe(event))
            surface.on_unknown = lambda message: echo(f"unknown message: {message.hex(' ')}")
            await asyncio.Event().wait()
    finally:
        for strip in surface.strips:
            strip.reset()
        await surface.settled()
        await surface.close()
