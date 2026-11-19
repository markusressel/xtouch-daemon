"""
A strip of an `empty` channel: dark, and its controls do nothing.
"""

from tests.support.audio import FakeBackend
from tests.support.hardware import RecordingSurface
from tests.support.strips import STATE, build, strips_of
from xtouch_daemon.hardware.protocol import Button, Color
from xtouch_daemon.strips import EmptyStrip
from xtouch_daemon.strips.base import StripEnv


async def test_an_empty_strip_is_dark_and_its_controls_do_nothing(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    (config,) = strips_of('[channel.x]\ntype = "empty"\n')
    strip = build(config, surface.strips[0], env)
    assert isinstance(strip, EmptyStrip)
    strip.update(STATE)
    assert surface.strips[0].color == Color.BLACK
    assert surface.strips[0].text == ["", ""]
    sent = list(surface.sent)

    strip.on_fader(0.5)
    strip.on_touch(True)
    strip.on_button(Button.MUTE, True)
    strip.on_encoder(1)
    strip.on_encoder_press(True)

    assert surface.sent == sent
    assert backend.calls == []
