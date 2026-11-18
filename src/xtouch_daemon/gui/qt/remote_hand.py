"""
The mouse as a hand on the device the daemon drives (the real one, or a virtual one another program hosts): what it
does on the drawing goes to the daemon as `live.Play` requests, which takes them as if the device sent them.
"""

from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import Play


class RemoteHand:
    """A `Hand` (see `Preview`) through the live view of the daemon."""

    def __init__(self, live: LiveView):
        self.live = live

    def touch(self, strip: int, touched: bool) -> None:
        self.live.send(Play(protocol.FaderTouched(strip, touched)))

    def move(self, strip: int, fraction: float, hand: bool = True) -> None:
        self.live.send(Play(protocol.FaderMoved(strip, protocol.fader_value(fraction))))

    def press(self, strip: int, button: Button, pressed: bool) -> None:
        self.live.send(Play(protocol.ButtonPressed(strip, button, pressed)))

    def turn(self, strip: int, steps: int) -> None:
        self.live.send(Play(protocol.EncoderTurned(strip, steps)))

    def push(self, strip: int, pressed: bool) -> None:
        self.live.send(Play(protocol.EncoderPressed(strip, pressed)))
