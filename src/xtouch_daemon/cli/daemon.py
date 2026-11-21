"""
Running the daemon (`run`), and the self-test of the device (`test`).
"""

import asyncio
import logging
from pathlib import Path

import click

from xtouch_daemon.audio.media import MprisPlayers
from xtouch_daemon.audio.pulse import PulseBackend
from xtouch_daemon.cli.options import CONFIG_OPTION, load_or_fail
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import default_config_path
from xtouch_daemon.daemon.lifecycle import Daemon, device_surface
from xtouch_daemon.hardware.selftest import run_selftest
from xtouch_daemon.live.device_test import TestRefused, run_test_in_daemon
from xtouch_daemon.live.log import LogBuffer
from xtouch_daemon.system import instance, systemd


@click.command()
@CONFIG_OPTION
@click.option(
    "-l",
    "--log-level",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default="info",
    show_default=True,
)
@click.option(
    "--virtual-device", is_flag=True, help="Drive the virtual device (`virtual-device`), as `[device] virtual = true`."
)
def run(config_path: Path | None, log_level: str, virtual_device: bool) -> None:
    """Run the daemon (in the foreground; `install-service` sets it up as a systemd user service)."""
    systemd.setup_logging(getattr(logging, log_level.upper()))
    with LogBuffer().attached() as log:
        _run(config_path, virtual_device, log)


def _run(config_path: Path | None, virtual_device: bool, log: LogBuffer) -> None:
    config = load_or_fail(config_path)
    try:
        daemon = Daemon(
            config,
            PulseBackend(),
            surface=device_surface(config.device.name, virtual=True) if virtual_device else None,
            config_path=config_path,
            live_socket=instance.socket_file(),
            players=MprisPlayers(),
            state_dir=instance.state_dir(),
            log=log,
        )
    except ConfigError as e:
        # e.g. the file with the MQTT password is missing
        raise click.ClickException(str(e)) from e
    try:
        with instance.registered(config_path or default_config_path()):
            asyncio.run(daemon.run())
    except instance.AlreadyRunning as e:
        raise click.ClickException(str(e)) from e


@click.command()
@CONFIG_OPTION
@click.option("--events/--no-events", default=True, help="Show what happens on the device after the test.")
@click.option(
    "--virtual-device",
    is_flag=True,
    help="Test the virtual device (`virtual-device`), as `[device] virtual = true` does.",
)
def test(config_path: Path | None, events: bool, virtual_device: bool) -> None:
    """
    Light up everything on the device and move the faders, then every strip answers its controls. While the daemon
    runs, the daemon tests the device it has, and its log shows the inputs.
    """
    if instance.running() is not None:
        _test_with_daemon(events)
        return
    config = load_or_fail(config_path)
    virtual = virtual_device or config.device.virtual
    try:
        surface = device_surface(config.device.name, virtual=True) if virtual else None
        asyncio.run(run_selftest(config.device.name, click.echo, show_events=events, surface=surface))
    except KeyboardInterrupt:
        pass
    except LookupError as e:
        if virtual:
            raise click.ClickException(f"{e}: start the virtual device first (`xtouch-daemon virtual-device`).") from e
        raise click.ClickException(
            f"{e}: is it switched on, in MC mode on USB? (No device at hand: `xtouch-daemon virtual-device` in "
            "another terminal, then `test --virtual-device`.)"
        ) from e
    except OSError as e:
        raise click.ClickException(
            f"can't open {config.device.name} ({e}). Is the daemon running? systemctl --user stop xtouch-daemon"
        ) from e


def _test_with_daemon(events: bool) -> None:
    if not events:
        raise click.ClickException(
            "The daemon runs: it tests the device until Ctrl+C. Stop it for the sweep alone (`--no-events`)."
        )
    click.echo(
        "The daemon runs: it tests the device. Its log shows every input (journalctl --user -u xtouch-daemon -f)."
    )
    try:
        asyncio.run(run_test_in_daemon(instance.socket_file(), click.echo))
    except KeyboardInterrupt:
        click.echo("The test ended: the device shows the slots again.")
    except TestRefused as e:
        raise click.ClickException(f"The daemon did not start the test: {e}") from e
    except OSError as e:
        raise click.ClickException(f"can't reach the daemon ({e})") from e
