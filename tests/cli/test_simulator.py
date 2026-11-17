"""
`virtual-device`.
"""

import logging

import pytest
from click.testing import CliRunner

from tests.support.cli import invoke
from xtouch_daemon import cli
from xtouch_daemon.simulator import server as server_module
from xtouch_daemon.simulator.server import AlreadyServed, VirtualDevice
from xtouch_daemon.system import instance, systemd


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[VirtualDevice]:
    """The virtual devices the command ran, without running them."""
    devices: list[VirtualDevice] = []

    async def run(self: VirtualDevice) -> None:
        devices.append(self)

    monkeypatch.setattr(server_module.VirtualDevice, "run", run)
    monkeypatch.setattr(systemd, "setup_logging", lambda level: None)
    return devices


def test_the_virtual_device_waits_where_the_daemon_looks(served: list[VirtualDevice]) -> None:
    invoke("virtual-device", "--broken-touch", "1,4")

    [device] = served
    assert device.path == instance.virtual_device_socket_file()
    assert device.device.broken_touch == {0, 3}


def test_it_logs_at_the_level_asked_for(served: list[VirtualDevice], monkeypatch: pytest.MonkeyPatch) -> None:
    levels: list[int] = []
    monkeypatch.setattr(systemd, "setup_logging", levels.append)

    invoke("virtual-device", "-l", "debug")

    assert levels == [logging.DEBUG]
    assert served[0].device.broken_touch == set()


@pytest.mark.parametrize(("value", "message"), [("one", "not a list of strips"), ("0,9", "the strips are 1 to 8")])
def test_broken_touch_takes_strips(served: list[VirtualDevice], value: str, message: str) -> None:
    result = CliRunner().invoke(cli.main, ["virtual-device", "--broken-touch", value])

    assert result.exit_code == 2
    assert message in result.output
    assert served == []


def test_a_second_virtual_device_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(self: VirtualDevice) -> None:
        raise AlreadyServed("a virtual device already runs at here")

    monkeypatch.setattr(server_module.VirtualDevice, "run", run)
    monkeypatch.setattr(systemd, "setup_logging", lambda level: None)

    result = CliRunner().invoke(cli.main, ["virtual-device"])

    assert result.exit_code == 1
    assert "already runs" in result.output
