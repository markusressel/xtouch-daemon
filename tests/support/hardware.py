"""
The device for the tests: a surface without device that records what it would send.
"""

import asyncio

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.surface import Surface


class RecordingSurface(Surface):
    """A surface whose messages are recorded instead of sent to a device."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[bytes] = []

    def send(self, message: bytes) -> None:
        self.sent.append(message)

    async def run(self) -> None:
        # never looks for the real device, which may be plugged in where the tests run
        await asyncio.Event().wait()

    def faders(self, strip: int) -> list[int]:
        return [m[1] | m[2] << 7 for m in self.sent if m[0] == 0xE0 | strip]

    def meters(self, strip: int) -> list[int]:
        return [m[1] & 0x0F for m in self.sent if m[0] == 0xD0 and m[1] >> 4 == strip]


def fader_value(fraction: float) -> int:
    return protocol.fader_value(fraction)


CARDS = """\
 0 [XTouchExt      ]: USB-Audio - X-Touch-Ext
                      BEHRINGER X-Touch-Ext at usb-0000:11:00.3-3.3, full speed
"""
