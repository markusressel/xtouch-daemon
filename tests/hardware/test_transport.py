"""
The ports of the device: the virtual device on a Unix socket.
"""

import asyncio
import socket
import tempfile
from pathlib import Path

import pytest

from xtouch_daemon.hardware.transport import AlsaPort, SocketPort


async def test_the_virtual_device_is_a_socket():
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        path = Path(directory) / "device.sock"
        port = SocketPort(path)
        # not running yet
        with pytest.raises(LookupError, match="does not run"):
            port.open(lambda data: None, lambda: None)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        # there, but not listening
        with pytest.raises(LookupError):
            port.open(lambda data: None, lambda: None)
        server.listen(1)
        received: list[bytes] = []
        closed: list[bool] = []
        transport, where = port.open(received.append, lambda: closed.append(True))
        assert where == str(path)
        connection, _ = server.accept()
        transport.write(b"\x90\x00\x7f")
        await transport.drain()
        assert connection.recv(16) == b"\x90\x00\x7f"
        connection.sendall(b"\x90\x68\x7f")
        for _ in range(100):
            if received:
                break
            await asyncio.sleep(0.01)
        assert received == [b"\x90\x68\x7f"]
        # the device goes away: unplugged
        connection.close()
        for _ in range(100):
            if closed:
                break
            await asyncio.sleep(0.01)
        assert closed == [True]
        server.close()


def test_a_socket_that_can_not_be_reached_is_an_error(tmp_path: Path):
    with pytest.raises(OSError, match="too long"):
        SocketPort(tmp_path / ("x" * 200)).open(lambda data: None, lambda: None)


def test_the_device_is_present_while_its_sound_card_is_there(tmp_path: Path):
    cards = tmp_path / "cards"
    cards.write_text(" 0 [XTouchExt      ]: USB-Audio - X-Touch-Ext\n")
    assert AlsaPort("X-Touch-Ext", proc_asound_cards=cards).present()
    assert not AlsaPort("Nothing", proc_asound_cards=cards).present()
    # no /proc/asound: no sound card at all
    assert not AlsaPort("X-Touch-Ext", proc_asound_cards=tmp_path / "gone").present()
