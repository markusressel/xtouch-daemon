"""
A controller gets another look and place when it moves to another strip: its label, color, LEDs, what its encoder
does and its volume range.
"""

from tests.support.audio import stream
from tests.support.hardware import RecordingSurface
from tests.support.strips import ID, STATE, make
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.hardware.protocol import Button, Color
from xtouch_daemon.strips.apps import AppGroupStrip, AutoStrip
from xtouch_daemon.strips.base import Look, StripEnv
from xtouch_daemon.strips.knobs import BalanceKnob, VolumeKnob


async def test_a_device_strip_takes_another_look_and_place(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, label="Out")
    strip.update(STATE)
    assert isinstance(strip.knob, VolumeKnob)
    strip.set_look(Look("Boxes", "red", indicators={Button.SOLO: "default"}))
    strip.set_place("balance", 10, 90)
    strip.update(STATE)
    assert surface.strips[0].text[0] == "Boxes"
    assert surface.strips[0].color == Color.RED
    assert strip.indicators == {Button.SOLO: "default"}
    assert isinstance(strip.knob, BalanceKnob)
    assert strip.volume_range() == (10, 90)
    # without a label of its own: the description of the device
    strip.set_look(Look())
    strip.update(STATE)
    assert surface.strips[0].text[0] == "speaker"


async def test_an_auto_strip_keeps_the_label_of_its_application(surface: RecordingSurface, env: StripEnv) -> None:
    strip = AutoStrip(surface.strips[0], env, ID, {}, Look())
    strip.assign("Spotify")
    strip.set_look(Look("Other", "green"))
    strip.update(AudioState(streams=(stream(1, "Spotify"),)))
    assert surface.strips[0].text[0] == "Spotify"
    assert surface.strips[0].color == Color.GREEN


async def test_an_apps_strip_takes_the_label_of_its_look(surface: RecordingSurface, env: StripEnv) -> None:
    strip = AppGroupStrip(surface.strips[0], env, ID, ("spotify",), Look("Music"))
    strip.set_look(Look("Tunes"))
    strip.update(AudioState())
    assert surface.strips[0].text[0] == "Tunes"
