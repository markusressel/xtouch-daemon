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
from xtouch_daemon.config.files import default_config_path, example_config
from xtouch_daemon.config.layout import LayoutConfig
from xtouch_daemon.config.layout_strips import InheritStripConfig, VoipStripConfig
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.strips import EmptyStripConfig, HomeAssistantStripConfig, StripConfig
from xtouch_daemon.config.values import DEFAULT_LAYOUT, MeterPoint, default_encoder
from xtouch_daemon.hardware import protocol


def describe_strip(config: StripConfig, number: int, meter_point: MeterPoint = "pre_fader") -> str:
    """What the strip does, for `check-config`; `meter_point` is where its meter takes the level (see `Config`)."""
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
            return f"{label}Home Assistant, entities *.*_{config.id or f'strip_{number}'}_* ({config.color})"
        case EmptyStripConfig():
            return "empty"
        case InheritStripConfig(layout=layout, strip=strip):
            where = f"layout {layout}" if layout is not None else "the default layout"
            return f"strip {strip} of {where}" if strip is not None else f"the strip of {where} at this place"
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
    _describe_strips(config)
    for layout in config.layouts:
        click.echo(f"Layout {layout.name}{f' ({layout.label})' if layout.label else ''}{describe_rules(layout)}:")
        _describe_strips(config, layout.name)


def _describe_strips(config: Config, layout: str = DEFAULT_LAYOUT) -> None:
    strips = config.all_strips(layout)
    for number, (strip, where) in enumerate(zip(strips, config.inherited(layout), strict=True), start=1):
        what = describe_strip(strip, number, config.meter_point(strip, layout))
        click.echo(f"  {number}. {what}{f', from {where}' if where else ''}")
    if len(strips) > protocol.STRIPS:
        click.echo(f"  The device shows the first {protocol.STRIPS} of them that don't collapse.")


def describe_rules(layout: LayoutConfig) -> str:
    """When the rules of a layout switch to it, e.g. ", while steam plays or mumble runs"."""
    rules = [
        *([f"{_any_of(layout.written('apps'), presets.Kind.STREAMS)} has a stream"] if layout.apps else []),
        *([f"{_any_of(layout.written('processes'), presets.Kind.PROCESSES)} runs"] if layout.processes else []),
    ]
    if not rules:
        return ""
    priority = f", priority {layout.priority}" if layout.priority else ""
    return f", while {' or '.join(rules)}{priority}"


def _any_of(entries: tuple[str, ...], kind: presets.Kind) -> str:
    """The entries of a rule, joined with "or", presets with what they stand for."""
    return " or ".join(presets.describe((entry,), kind) for entry in entries)


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
