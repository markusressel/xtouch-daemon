"""
The configuration file: writing the example (`init-config`), checking it and telling what each strip does
(`check-config`), and its JSON Schema for editors (`schema`).
"""

import shlex
from pathlib import Path
from typing import assert_never

import click

from xtouch_daemon.cli.options import CONFIG_OPTION, load_or_fail
from xtouch_daemon.config import presets
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.bindings import describe_part, fill, placeholders_of
from xtouch_daemon.config.buttons import BUTTON_NAMES, describe_action
from xtouch_daemon.config.files import default_config_path, example_config
from xtouch_daemon.config.json_schema import schema_text
from xtouch_daemon.config.strips import (
    CUSTOM_BUTTONS,
    CustomStripConfig,
    EmptyStripConfig,
    HomeAssistantStripConfig,
    StripConfig,
)
from xtouch_daemon.config.values import MeterPoint, default_encoder
from xtouch_daemon.config.voip_strips import VoipStripConfig
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.slots.outcomes import notes, outcomes, table


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
                ", select makes it the default" if config.button("select").press == "default" else ""
            )
        case AppsStripConfig():
            what = "applications " + presets.describe(config.written("match"), presets.Kind.STREAMS)
        case AutoStripConfig():
            what = "the next application that plays"
        case HomeAssistantStripConfig():
            label = f"{config.label!r} " if config.label else ""
            return f"{label}Home Assistant, entities *.*_{name}_* ({config.color})"
        case CustomStripConfig():
            return _custom_text(config)
        case EmptyStripConfig():
            return "empty"
        case VoipStripConfig():
            label = f"{config.label!r} " if config.label else ""
            who = f"{' or '.join(config.person)} in the voice chat"
            return f"{label}{who}, dark while away ({config.color}, talking: {config.talking_color})"
        case _ as unreachable:
            assert_never(unreachable)
    label = f"{config.label!r} " if isinstance(config, DeviceStripConfig | AppsStripConfig) and config.label else ""
    details = [_color_text(config.color)]
    if config.meter is False:
        details.append("no meter")
    elif config.meter is not True:
        details.append(f"meter: {describe_part(config.meter)}")
    elif meter_point == "post_fader":
        details.append("meter post-fader")
    if config.lcd is not None:
        details.append(f"lcd: {describe_part(config.lcd)}")
    details += _buttons_text(config)
    encoder = config.encoder if config.encoder is not None else default_encoder(config.type, config.fader)
    details.append(f"encoder: {describe_part(encoder)}")
    if config.fader != "volume":
        details.append(f"fader: {describe_part(config.fader)}")
    if (
        not isinstance(config, DeviceStripConfig)
        and config.launch is not None
        and config.button("select").press == "launch"
    ):
        when = "also while it runs" if config.launch_when_running else "while it does not run"
        what += f", select launches {shlex.join(config.launch)} {when}"
    return f"{label}{what} ({', '.join(details)})"


def _buttons_text(config: DeviceStripConfig | AppsStripConfig | AutoStripConfig) -> list[str]:
    """
    What Rec and Solo show (their LED, or the profiles Rec switches), and what the buttons do beyond what the type
    does by default (Select making the device the default or launching is said with what the strip is).
    """
    texts: list[str] = []
    for name in BUTTON_NAMES:
        setup = config.button(name)
        if (
            isinstance(config, DeviceStripConfig)
            and config.profiles
            and setup.press == "profile"
            and setup.led == "press"
        ):
            texts.append(f"{name}: profile {' / '.join(p.label for p in config.profiles)}")
            continue
        acts = [
            f"{part} {describe_action(action)}"
            for part, action in (("press", setup.press), ("hold", setup.hold))
            if action != "off" and not (name == "select" and part == "press" and action in ("default", "launch"))
        ]
        if acts:
            texts.append(f"{name}: {', '.join(acts)}, LED {describe_part(setup.led)}")
        elif name != "select":
            texts.append(f"{name}: {describe_part(setup.led)}")
    return texts


def _color_text(color: object) -> str:
    return color if isinstance(color, str) else f"color: {describe_part(color)}"


def _custom_text(config: CustomStripConfig) -> str:
    """What a custom channel does: what each part is bound to."""
    label = f"{config.label!r} " if config.label else ""
    parts: dict[str, object] = {"fader": config.fader, "encoder": config.encoder, "lcd": config.lcd}
    parts |= {"meter": config.meter, "present": config.present}
    details = [_color_text(config.color)]
    details += [f"{name}: {describe_part(part)}" for name, part in parts.items() if part is not None]
    for name in CUSTOM_BUTTONS:
        setup = config.button(name)
        actions = (("press", setup.press), ("hold", setup.hold))
        acts = [f"{part} {describe_part(action)}" for part, action in actions if action != "off"]
        if acts or setup.led != "off":
            details.append(f"{name}: {', '.join([*acts, f'LED {describe_part(setup.led)}'])}")
    targets = f" for {', '.join(target.name for target in config.targets)}" if config.targets else ""
    together = " together" if config.together else ""
    return f"{label}custom{targets}{together} ({', '.join(details)})"


def describe_targets(config: StripConfig) -> list[str]:
    """
    The programs of each target of a custom channel, with `{target}` filled in (`{value}` stays: a hand gives it),
    for `check-config`: one line per target, none without targets.
    """
    if not isinstance(config, CustomStripConfig):
        return []
    programs = {where: argv for where, argv in config.programs().items() if "target" in placeholders_of(argv)}
    return [
        f"{target.name}: "
        + "; ".join(f"{where} {shlex.join(fill(argv, target=target.value))}" for where, argv in programs.items())
        for target in config.targets
    ]


ROWS_SHOWN = 12
"""The most rows of the table of outcomes that `check-config` shows without `--all`."""


@click.command("check-config")
@CONFIG_OPTION
@click.option("--all", "every_row", is_flag=True, help="Show every combination of the table, however many there are.")
def check_config(config_path: Path | None, every_row: bool) -> None:
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
        for line in describe_targets(strip):
            click.echo(f"    {line}")
    click.echo("What the slots show:")
    rows = outcomes(setup.scene)
    # a long table is as hard to read as none: the situations that differ in one thing, the rest on request
    shown = rows
    if len(rows) > ROWS_SHOWN and not every_row:
        shown = [row for row in rows if (row.mode != DEFAULT) + len(row.on) + len(row.flipped) <= 1]
    click.echo(table(shown))
    if len(shown) < len(rows):
        click.echo(f"  ({len(rows) - len(shown)} more combinations of these: check-config --all)")
    if found := notes(setup.scene):
        click.echo("Notes:")
        for note in found:
            click.echo(f"  {note}")


@click.command("init-config")
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


@click.command("schema")
def schema() -> None:
    """
    Print the JSON Schema of the configuration file. Editors with a TOML language server (Taplo, Tombi) complete
    options from it, show their help and mark mistakes; the example configuration points to the published one.
    """
    click.echo(schema_text(), nl=False)
