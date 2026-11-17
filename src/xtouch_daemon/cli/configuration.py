"""
The configuration file: writing the example (`init-config`), and checking it and telling what each strip does
(`check-config`).
"""

import shlex
from pathlib import Path
from typing import assert_never

import click

from xtouch_daemon.cli.options import CONFIG_OPTION, load_or_fail
from xtouch_daemon.config import presets
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import default_config_path, example_config, slots_example_config
from xtouch_daemon.config.layout_strips import VoipStripConfig
from xtouch_daemon.config.migrate import migrate
from xtouch_daemon.config.strips import EmptyStripConfig, HomeAssistantStripConfig, StripConfig
from xtouch_daemon.config.values import MeterPoint, default_encoder
from xtouch_daemon.slots.outcomes import outcomes, table


def describe_strip(config: StripConfig, name: str, meter_point: MeterPoint = "pre_fader") -> str:
    """
    What the strip of a channel does, for `check-config`; `name` is the channel's (that of its entities),
    `meter_point` where its meter takes the level.
    """
    match config:
        case DeviceStripConfig(choices=choices) if choices:
            titles = [choice.title for choice in choices]
            either = f"{', '.join(titles[:-1])} or {titles[-1]}" if len(titles) > 1 else titles[0]
            what = f"{config.type}: {either} (Select switches)"
        case DeviceStripConfig(device=()):
            what = f"the default {config.type}"
        case DeviceStripConfig():
            what = f"{config.type} {' or '.join(config.device)}" + (
                ", select makes it the default" if config.select else ""
            )
        case AppsStripConfig():
            what = "applications " + presets.describe(config.written("match"), presets.Kind.STREAMS)
        case AutoStripConfig():
            what = "the next application that plays"
        case HomeAssistantStripConfig():
            label = f"{config.label!r} " if config.label else ""
            return f"{label}Home Assistant, entities *.*_{name}_* ({config.color})"
        case EmptyStripConfig():
            return "empty"
        case VoipStripConfig():
            launch = f", select launches {shlex.join(config.launch)} while it is not there" if config.launch else ""
            collapse = ", collapses" if config.collapse else ""
            colors = f"{config.color}, talking: {config.talking_color}"
            if config.person:
                who = f"{' or '.join(config.person)} in the voice chat"
                label = f"{config.label!r} " if config.label else ""
                return f"{label}{who}, dark while away ({colors}{collapse}){launch}"
            return f"a participant of the voice chat, in the group ({colors}{collapse}){launch}"
        case _ as unreachable:
            assert_never(unreachable)
    label = f"{config.label!r} " if isinstance(config, DeviceStripConfig | AppsStripConfig) and config.label else ""
    details = [config.color, *([] if config.meter else ["no meter"])]
    if config.meter and meter_point == "post_fader":
        details.append("meter post-fader")
    rec = (
        f"profile {' / '.join(p.label for p in config.profiles)}"
        if isinstance(config, DeviceStripConfig) and config.profiles
        else config.rec
    )
    details += [f"{button}: {indicator}" for button, indicator in (("rec", rec), ("solo", config.solo))]
    details.append(f"encoder: {config.encoder or default_encoder(config.type, config.fader)}")
    if config.fader != "volume":
        details.append(f"fader: {config.fader}")
    if not isinstance(config, DeviceStripConfig) and config.launch is not None:
        when = "also while it runs" if config.launch_when_running else "while it does not run"
        what += f", select launches {shlex.join(config.launch)} {when}"
    if config.collapse:
        details.append("collapses")
    return f"{label}{what} ({', '.join(details)})"


@click.command("check-config")
@CONFIG_OPTION
def check_config(config_path: Path | None) -> None:
    """Check the configuration and show what each strip does."""
    path = config_path or default_config_path()
    config = load_or_fail(config_path)
    source = str(path) if path.exists() else "No configuration file, the defaults"
    click.echo(f"{source}: valid")
    setup = config.slots
    if setup.channels:
        click.echo("Channels:")
    for name, strip in setup.channels.items():
        meter_point = getattr(strip, "meter_point", None) or config.behavior.meter_point
        click.echo(f"  {name}: {describe_strip(strip, name, meter_point)}")
    click.echo("What the slots show:")
    click.echo(table(outcomes(setup.scene)))


@click.command("init-config")
@click.argument("path", type=click.Path(path_type=Path, dir_okay=False), required=False)
@click.option("-f", "--force", is_flag=True, help="Overwrite an existing file.")
@click.option(
    "--strips", is_flag=True, help="The example with strips and layouts (for the GUI, which edits only those)."
)
def init_config(path: Path | None, force: bool, strips: bool) -> None:
    """Write the example configuration (to the default path, or PATH)."""
    path = path or default_config_path()
    if path.exists() and not force:
        raise click.ClickException(f"{path} exists already (--force overwrites it)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example_config() if strips else slots_example_config(), encoding="utf-8")
    click.echo(f"Wrote {path}. Edit it, then check it with: xtouch-daemon check-config")


@click.command("migrate-config")
@CONFIG_OPTION
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Where to write the new file [default: next to it, <name>.slots.toml].",
)
@click.option("--in-place", is_flag=True, help="Replace the file; the old one stays as <name>.layouts.toml.")
@click.option("-f", "--force", is_flag=True, help="Overwrite an existing output file.")
def migrate_config(config_path: Path | None, output: Path | None, in_place: bool, force: bool) -> None:
    """Write a file with strips and layouts as channels, states and slots, and tell what changed."""
    path = config_path or default_config_path()
    if output is not None and in_place:
        raise click.ClickException("--output or --in-place, not both")
    try:
        migration = migrate(path.read_text(encoding="utf-8"), str(path))
    except FileNotFoundError:
        raise click.ClickException(f"{path} does not exist") from None
    except ConfigError as e:
        raise click.ClickException(str(e)) from e
    backup = path.with_name(f"{path.stem}.layouts{path.suffix}")
    target = path if in_place else output or path.with_name(f"{path.stem}.slots{path.suffix}")
    for existing in (backup if in_place else target,):
        if existing.exists() and not force:
            raise click.ClickException(f"{existing} exists already (--force overwrites it)")
    if in_place:
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        click.echo(f"Kept the old file as {backup}")
    target.write_text(migration.text, encoding="utf-8")
    click.echo(f"Wrote {target}")
    for note in migration.notes:
        click.echo(f"  - {note}")
    click.echo(f"Check it with: xtouch-daemon check-config -c {target}")
