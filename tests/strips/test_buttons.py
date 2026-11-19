"""
What the buttons of a strip do by their tables: the modes and states of the slots, push to talk, muting the others,
an action on hold, and what their LEDs show for it.
"""

import dataclasses
import logging

import pytest

from tests.support.audio import FakeBackend, output
from tests.support.hardware import RecordingSurface
from tests.support.strips import ID
from tests.support.tasks import settle
from tests.support.waiting import until
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config.buttons import ButtonSetup
from xtouch_daemon.hardware.protocol import Button, Led
from xtouch_daemon.strips.base import Look, StripController, StripEnv
from xtouch_daemon.strips.device import DeviceStrip

MUTED = AudioState(outputs=(output("speaker", 50, muted=True),))


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


def strip_with(surface: RecordingSurface, env: StripEnv, **buttons: ButtonSetup) -> DeviceStrip:
    look = Look(None, "cyan", buttons={Button[name.upper()]: setup for name, setup in buttons.items()})
    return DeviceStrip(surface.strips[0], env, ID, Direction.OUTPUT, ("speaker",), look)


def press(strip: StripController, button: Button) -> None:
    strip.on_button(button, True)
    strip.on_button(button, False)


async def test_buttons_choose_the_modes_and_states_of_the_slots(surface: RecordingSurface, env: StripEnv) -> None:
    actions = Actions()
    strip = strip_with(
        surface,
        dataclasses.replace(env, actions=actions),
        rec=ButtonSetup("cycle_modes", led="press"),
        solo=ButtonSetup("mode:gaming", led="press"),
        select=ButtonSetup("toggle:call", led="press"),
    )
    strip.update(MUTED)
    leds = surface.strips[0].leds
    assert [leds[Button.REC], leds[Button.SOLO], leds[Button.SELECT]] == [Led.OFF, Led.OFF, Led.OFF]

    press(strip, Button.SOLO)
    press(strip, Button.SELECT)
    assert [leds[Button.REC], leds[Button.SOLO], leds[Button.SELECT]] == [Led.ON, Led.ON, Led.ON]
    press(strip, Button.REC)

    assert actions.calls == ["mode gaming", "toggle call", "cycle"]
    assert [leds[Button.REC], leds[Button.SOLO]] == [Led.OFF, Led.OFF]


async def test_without_the_slots_the_buttons_of_modes_are_dark_and_say_why(
    surface: RecordingSurface, env: StripEnv, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    strip = strip_with(surface, env, solo=ButtonSetup("mode:gaming", led="press"))
    strip.update(MUTED)

    press(strip, Button.SOLO)

    assert surface.strips[0].leds[Button.SOLO] == Led.OFF
    assert "mode:gaming needs the slots" in caplog.text


async def test_push_to_talk_unmutes_while_held(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = strip_with(surface, env, select=ButtonSetup("talk", led="press"))
    strip.update(MUTED)

    strip.on_button(Button.SELECT, True)
    assert surface.strips[0].leds[Button.SELECT] == Led.ON
    strip.on_button(Button.SELECT, False)
    await settle()

    assert surface.strips[0].leds[Button.SELECT] == Led.OFF
    assert backend.calls == [
        ("set_device_mute", Direction.OUTPUT, "speaker", False),
        ("set_device_mute", Direction.OUTPUT, "speaker", True),
    ]


async def test_push_to_talk_leaves_a_device_alone_that_is_not_muted(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = strip_with(surface, env, select=ButtonSetup("talk"))
    strip.update(AudioState(outputs=(output("speaker", 50),)))

    press(strip, Button.SELECT)
    await settle()

    assert backend.calls == []


async def test_mute_others_mutes_the_other_strips_while_held(surface: RecordingSurface, env: StripEnv) -> None:
    solos: list[bool] = []
    strip = strip_with(
        surface, dataclasses.replace(env, solo=lambda _, on: solos.append(on)), solo=ButtonSetup("mute_others")
    )
    strip.update(MUTED)

    press(strip, Button.SOLO)
    # a strip that goes away lets go of what its buttons hold
    strip.on_button(Button.SOLO, True)
    strip.close()

    assert solos == [True, False, True, False]


async def test_a_button_does_one_thing_on_a_press_and_another_on_hold(surface: RecordingSurface, env: StripEnv) -> None:
    actions = Actions()
    strip = strip_with(
        surface, dataclasses.replace(env, actions=actions), rec=ButtonSetup("cycle_modes", hold="mode:night")
    )
    strip.update(MUTED)

    press(strip, Button.REC)
    strip.on_button(Button.REC, True)
    await until(lambda: len(actions.calls) == 2)
    strip.on_button(Button.REC, False)
    # pressed again, and the strip goes away before the hold
    strip.on_button(Button.REC, True)
    strip.on_button(Button.REC, True)
    strip.close()
    await settle()

    assert actions.calls == ["cycle", "mode night"]


async def test_a_button_without_an_action_does_nothing(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = strip_with(surface, env, solo=ButtonSetup("off", led="press"))
    strip.update(MUTED)

    press(strip, Button.SOLO)
    press(strip, Button.REC)

    assert surface.strips[0].leds[Button.SOLO] == Led.OFF
    assert backend.calls == []
