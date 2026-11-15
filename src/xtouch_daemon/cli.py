"""The command line: running the daemon, and the tools around it (configuration, devices, applications, a test)."""

import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, assert_never

import click

from xtouch_daemon import __version__, systemd
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.audio.pulse import PulseBackend
from xtouch_daemon.config import (
    AppsStripConfig,
    AutoStripConfig,
    Config,
    ConfigError,
    DeviceStripConfig,
    EmptyStripConfig,
    HomeAssistantStripConfig,
    StripConfig,
    default_config_path,
    example_config,
    load_config,
)
from xtouch_daemon.daemon import Daemon
from xtouch_daemon.selftest import run_selftest

CONFIG_OPTION = click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help=f"The configuration file [default: {default_config_path()}]",
)


def _load(config_path: Path | None) -> Config:
    try:
        return load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e


async def _snapshot() -> AudioState:
    import pulsectl_asyncio

    async with pulsectl_asyncio.PulseAsync("xtouch-daemon-cli") as pulse:
        return await PulseBackend.snapshot(pulse)


def _audio_state() -> AudioState:
    try:
        return asyncio.run(_snapshot())
    except Exception as e:
        raise click.ClickException(f"can't reach the sound server (is pipewire-pulse running?): {e}") from e


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="xtouch-daemon")
def main() -> None:
    """Use a Behringer X-Touch Extender as a hardware mixer for PipeWire."""


@main.command()
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
    config = _load(config_path)
    try:
        daemon = Daemon(config, PulseBackend(), config_path=config_path)
    except ConfigError as e:
        # e.g. the file with the MQTT password is missing
        raise click.ClickException(str(e)) from e
    asyncio.run(daemon.run())


def describe_strip(config: StripConfig, number: int) -> str:
    match config:
        case DeviceStripConfig(device=None):
            what = f"the default {config.type}"
        case DeviceStripConfig():
            what = f"{config.type} {config.device}" + (", select makes it the default" if config.select else "")
        case AppsStripConfig():
            what = "applications " + ", ".join(config.match)
        case AutoStripConfig():
            what = "the next application that plays"
        case HomeAssistantStripConfig():
            label = f"{config.label!r} " if config.label else ""
            return f"{label}Home Assistant, entities *.*_{config.id or f'strip_{number}'}_* ({config.color})"
        case EmptyStripConfig():
            return "empty"
        case _ as unreachable:
            assert_never(unreachable)
    label = f"{config.label!r} " if isinstance(config, DeviceStripConfig | AppsStripConfig) and config.label else ""
    details = [config.color, *([] if config.meter else ["no meter"])]
    details += [f"{button}: {indicator}" for button, indicator in (("rec", config.rec), ("solo", config.solo))]
    return f"{label}{what} ({', '.join(details)})"


@main.command("check-config")
@CONFIG_OPTION
def check_config(config_path: Path | None) -> None:
    """Check the configuration and show what each strip does."""
    path = config_path or default_config_path()
    config = _load(config_path)
    source = str(path) if path.exists() else "No configuration file, the defaults"
    click.echo(f"{source}: valid")
    for number, strip in enumerate(config.all_strips(), start=1):
        click.echo(f"  {number}. {describe_strip(strip, number)}")


@main.command("init-config")
@click.argument("path", type=click.Path(path_type=Path, dir_okay=False), required=False)
@click.option("-f", "--force", is_flag=True, help="Overwrite an existing file.")
def init_config(path: Path | None, force: bool) -> None:
    """Write the example configuration (to the default path, or PATH)."""
    path = path or default_config_path()
    if path.exists() and not force:
        raise click.ClickException(f"{path} exists already (--force overwrites it)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example_config(), encoding="utf-8")
    click.echo(f"Wrote {path}. Edit it, then check it with: xtouch-daemon check-config")


@main.command("list-devices")
def list_devices() -> None:
    """List the outputs and inputs, with the names to use as `device` (* marks the defaults)."""
    state = _audio_state()
    for direction, title in ((Direction.OUTPUT, "Outputs"), (Direction.INPUT, "Inputs")):
        click.echo(f"{title}:")
        for device in state.devices(direction):
            marker = "*" if state.is_default(device) else " "
            flags = ", ".join(flag for flag, on in (("muted", device.muted), ("running", device.running)) if on)
            click.echo(f"  {marker} {device.name}")
            click.echo(f"      {device.description}, {device.volume}%{', ' + flags if flags else ''}")


def strip_for(app_matches: Any, config: Config) -> str:
    for number, strip in enumerate(config.all_strips(), start=1):
        if isinstance(strip, AppsStripConfig) and app_matches(strip.match):
            return f"strip {number} ({strip.label})"
    if any(app_matches((pattern,)) for pattern in config.behavior.ignore):
        return "ignored"
    if any(isinstance(strip, AutoStripConfig) for strip in config.all_strips()):
        return "an auto strip"
    return "no strip"


@main.command("list-apps")
@CONFIG_OPTION
def list_apps(config_path: Path | None) -> None:
    """List the applications that play now, and which strip takes them."""
    config = _load(config_path)
    state = _audio_state()
    if not state.streams:
        click.echo("No application plays right now.")
        return
    for stream in state.streams:
        alias = config.aliases.get(stream.app)
        name = f"{stream.app} (shown as {alias!r})" if alias else stream.app
        paused = ", paused" if stream.corked else ""
        click.echo(f"  {name}  binary: {stream.binary or '-'}, {stream.volume}%{paused}")
        click.echo(f"      goes to {strip_for(stream.matches, config)}")


@main.command()
@CONFIG_OPTION
@click.option("--events/--no-events", default=True, help="Show what happens on the device after the test.")
def test(config_path: Path | None, events: bool) -> None:
    """Light up everything on the device and move the faders (stop the daemon first)."""
    config = _load(config_path)
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


@main.command("install-service")
@click.option("--now", is_flag=True, help="Also enable and start it.")
def install_service(now: bool) -> None:
    """Set the daemon up as a systemd user service."""
    executable = shutil.which("xtouch-daemon") or str(Path(sys.argv[0]).resolve())
    path = systemd.unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(systemd.unit_file(executable), encoding="utf-8")
    click.echo(f"Wrote {path}")
    commands = [["systemctl", "--user", "daemon-reload"]]
    if now:
        commands.append(["systemctl", "--user", "enable", "--now", systemd.UNIT_NAME])
    for command in commands:
        subprocess.run(command, check=True)
    if not now:
        click.echo(f"Start it with: systemctl --user enable --now {systemd.UNIT_NAME}")
    click.echo("Logs: journalctl --user -u xtouch-daemon -f")
