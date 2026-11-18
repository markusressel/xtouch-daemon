"""
The sound server: its devices (`list-devices`) and the applications that play, with the strips that take them
(`list-apps`).
"""

import re
from pathlib import Path
from typing import Any

import click

from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.audio.pulse import SoundServerError, read_state
from xtouch_daemon.cli.options import CONFIG_OPTION, load_or_fail
from xtouch_daemon.config import presets
from xtouch_daemon.config.model import Config
from xtouch_daemon.slots.model import APPS, AUTO


def _audio_state() -> AudioState:
    try:
        return read_state("xtouch-daemon-cli")
    except SoundServerError as e:
        raise click.ClickException(str(e)) from e


def snippet(state: AudioState) -> str:
    """A channel for each output and input, to paste into the configuration: Bluetooth devices by a wildcard."""
    blocks: list[str] = []
    seen: set[str] = set()
    for direction in (Direction.OUTPUT, Direction.INPUT):
        for device in state.devices(direction):
            bluetooth = device.name.startswith("bluez_")
            name = f"bluez_{direction.value}.*" if bluetooth else device.name
            if name in seen:
                continue
            seen.add(name)
            words = re.sub(r"[^a-z0-9]+", "_", device.description.lower()).strip("_")
            ident = f"{direction.value}_{'_'.join(words.split('_')[:2])}".strip("_")
            note = "  # any Bluetooth device" if bluetooth else ""
            blocks.append(
                f'[channel.{ident}]\ntype = "{direction.value}"\ndevice = "{name}"{note}\n# {device.description}'
            )
    return "\n\n".join(blocks)


@click.command("list-devices")
@click.option("--snippet", "as_snippet", is_flag=True, help="Print a channel for each device, to paste into the file.")
def list_devices(as_snippet: bool) -> None:
    """
    List the outputs and inputs, with the names to use as `device` (* marks the defaults), and the sound cards with
    their profiles (* marks the active ones), for `card` and `profile` of `choices`. With `--snippet`: a channel for
    each device instead.
    """
    state = _audio_state()
    if as_snippet:
        click.echo(snippet(state))
        return
    for direction, title in ((Direction.OUTPUT, "Outputs"), (Direction.INPUT, "Inputs")):
        click.echo(f"{title}:")
        for device in state.devices(direction):
            marker = "*" if state.is_default(device) else " "
            flags = ", ".join(flag for flag, on in (("muted", device.muted), ("running", device.running)) if on)
            click.echo(f"  {marker} {device.name}")
            click.echo(f"      {device.description}, {device.volume}%{', ' + flags if flags else ''}")
    for card in state.cards:
        devices = [device.name for device in (*state.outputs, *state.inputs) if device.card == card.name]
        description = f", {card.description}" if card.description else ""
        click.echo(f"Profiles of {card.name}{description}{' (' + ', '.join(devices) + ')' if devices else ''}:")
        for profile in card.profiles:
            marker = "*" if profile.name == card.profile else " "
            click.echo(f"  {marker} {profile.name}")
            click.echo(f"      {profile.description}")


def strip_for(app_matches: Any, config: Config) -> str:
    """Where an application goes: the `apps` channel that has it, `apps` or `auto` (unless excluded), or nowhere."""
    scene = config.slots.scene
    for name, channel in scene.channels.items():
        if channel.type == "apps" and app_matches(channel.streams):
            label = getattr(config.slots.channels.get(name), "label", None)
            return f"channel {name}" + (f" ({label})" if label else "")
    excluded = presets.expand(scene.apps.exclude, presets.Kind.STREAMS)
    if any(app_matches((pattern,)) for pattern in excluded):
        return "ignored"
    shown = {candidate.show for stack in scene.stacks.values() for candidate in stack}
    if AUTO in shown:
        return "an auto slot"
    if APPS in shown:
        return "an apps slot"
    return "no slot"


@click.command("list-apps")
@CONFIG_OPTION
def list_apps(config_path: Path | None) -> None:
    """List the applications that play now, and which channel or slot takes them."""
    config = load_or_fail(config_path)
    state = _audio_state()
    if not state.streams:
        click.echo("No application plays right now.")
        return
    for stream in state.streams:
        alias = config.aliases.get(stream.app)
        name = f"{stream.app} (shown as {alias!r})" if alias else stream.app
        groups = presets.matching_stream(stream.app, stream.binary)
        name += f" ({', '.join(groups)})" if groups else ""
        paused = ", paused" if stream.corked else ""
        click.echo(f"  {name}  binary: {stream.binary or '-'}, {stream.volume}%{paused}")
        click.echo(f"      goes to {strip_for(stream.matches, config)}")
