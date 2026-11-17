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
from xtouch_daemon.hardware.selftest import run_selftest
from xtouch_daemon.runtime.daemon import Daemon
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
def run(config_path: Path | None, log_level: str) -> None:
    """Run the daemon (in the foreground; `install-service` sets it up as a systemd user service)."""
    systemd.setup_logging(getattr(logging, log_level.upper()))
    config = load_or_fail(config_path)
    try:
        daemon = Daemon(
            config,
            PulseBackend(),
            config_path=config_path,
            live_socket=instance.socket_file(),
            players=MprisPlayers(),
            state_dir=instance.state_dir(),
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
def test(config_path: Path | None, events: bool) -> None:
    """Light up everything on the device and move the faders (stop the daemon first)."""
    config = load_or_fail(config_path)
    try:
        asyncio.run(run_selftest(config.device.name, click.echo, show_events=events))
    except KeyboardInterrupt:
        pass
    except LookupError as e:
        raise click.ClickException(f"{e}: is it switched on, in MC mode on USB?") from e
    except OSError as e:
        raise click.ClickException(
            f"can't open {config.device.name} ({e}). Is the daemon running? systemctl --user stop xtouch-daemon"
        ) from e
