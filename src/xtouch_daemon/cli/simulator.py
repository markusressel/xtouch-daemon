"""
The virtual device (`virtual-device`): a simulated X-Touch Extender for the daemon to drive, without the device.
"""

import asyncio
import contextlib
import logging

import click

from xtouch_daemon.hardware import protocol
from xtouch_daemon.simulator.device import SimulatedDevice
from xtouch_daemon.simulator.server import AlreadyServed, VirtualDevice
from xtouch_daemon.system import instance, systemd


def _strips(value: str) -> frozenset[int]:
    """`1,4` is the strips 1 and 4 (from 0: 0 and 3)."""
    try:
        numbers = {int(part) for part in value.split(",") if part.strip()}
    except ValueError as e:
        raise click.BadParameter(f"{value!r} is not a list of strips like 1,4") from e
    if not numbers <= set(range(1, protocol.STRIPS + 1)):
        raise click.BadParameter(f"the strips are 1 to {protocol.STRIPS}")
    return frozenset(number - 1 for number in numbers)


@click.command("virtual-device")
@click.option(
    "--broken-touch", default="", metavar="STRIPS", help="Faders whose touch sensor failed, e.g. 1,4 (from 1)."
)
@click.option(
    "-l",
    "--log-level",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default="info",
    show_default=True,
    help="debug: also every message of the daemon.",
)
def virtual_device(broken_touch: str, log_level: str) -> None:
    """
    Run a virtual X-Touch Extender for `run --virtual-device` (or `[device] virtual = true`), headless. The GUI shows
    what it shows, as for the real device.
    """
    systemd.setup_logging(getattr(logging, log_level.upper()))
    server = VirtualDevice(SimulatedDevice(broken_touch=_strips(broken_touch)), instance.virtual_device_socket_file())
    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(server.run())
    except AlreadyServed as e:
        raise click.ClickException(str(e)) from e
