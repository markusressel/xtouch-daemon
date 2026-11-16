"""The command line: running the daemon, and the tools around it (configuration, devices, applications, a test)."""

import asyncio
import logging
import shlex
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO, assert_never

import click

from xtouch_daemon import __version__, instance, live, mumble, systemd
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.audio.pulse import PulseBackend, SoundServerError, read_state
from xtouch_daemon.config import presets
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import default_config_path, example_config, load_config
from xtouch_daemon.config.layout import LayoutConfig
from xtouch_daemon.config.layout_strips import InheritStripConfig, VoipStripConfig
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.strips import EmptyStripConfig, HomeAssistantStripConfig, StripConfig
from xtouch_daemon.config.values import DEFAULT_LAYOUT, MeterPoint, default_encoder
from xtouch_daemon.daemon import Daemon
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.selftest import run_selftest
from xtouch_daemon.live import Reply, Snapshot
from xtouch_daemon.media import MprisPlayers

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


def _audio_state() -> AudioState:
    try:
        return read_state("xtouch-daemon-cli")
    except SoundServerError as e:
        raise click.ClickException(str(e)) from e


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
        daemon = Daemon(
            config,
            PulseBackend(),
            config_path=config_path,
            live_socket=instance.socket_file(),
            players=MprisPlayers(),
            layout_file=instance.layout_file(),
        )
    except ConfigError as e:
        # e.g. the file with the MQTT password is missing
        raise click.ClickException(str(e)) from e
    try:
        with instance.registered(config_path or default_config_path()):
            asyncio.run(daemon.run())
    except instance.AlreadyRunning as e:
        raise click.ClickException(str(e)) from e


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


@main.command("check-config")
@CONFIG_OPTION
def check_config(config_path: Path | None) -> None:
    """Check the configuration and show what each strip does."""
    path = config_path or default_config_path()
    config = _load(config_path)
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


LAYOUT_TIMEOUT = 3.0
"""Seconds `layout` waits for the daemon to show the layout."""


def _live_lines(lines: BinaryIO) -> Iterator[Snapshot | Reply]:
    """The snapshots and replies of the live view, until the daemon closes the connection."""
    for line in lines:
        message = live.decode_message(line)
        if message is not None:
            yield message


@main.command()
@click.argument("name", required=False)
@click.option("--next", "step", flag_value=1, type=int, help="Switch to the next layout.")
@click.option("--previous", "step", flag_value=-1, type=int, help="Switch to the previous layout.")
def layout(name: str | None, step: int | None) -> None:
    """List the layouts of the running daemon, or switch it to the layout NAME (or the next or previous one)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(LAYOUT_TIMEOUT)
        try:
            sock.connect(str(instance.socket_file()))
        except OSError as e:
            raise click.ClickException(f"the daemon does not run, or is older than this program ({e.strerror})") from e
        _switch_layout(sock, name, step)


def _switch_layout(sock: socket.socket, name: str | None, step: int | None) -> None:
    with sock.makefile("rb") as lines:
        messages = _live_lines(lines)
        try:
            current = next(message for message in messages if isinstance(message, Snapshot))
        except (StopIteration, TimeoutError) as e:
            raise click.ClickException("the daemon did not answer") from e
        names = current.layouts or ("default",)
        if name is None and step is None:
            for each in names:
                click.echo(f"{'*' if each == current.layout else ' '} {each}")
            return
        if name is not None and name not in names:
            raise click.ClickException(f"there is no layout {name} ({', '.join(names)})")
        if "layout" not in current.features:
            raise click.ClickException("the daemon is older than this program, restart it")
        active = current.layout or names[0]
        wanted = name if name is not None else names[(names.index(active) + (step or 0)) % len(names)]
        sock.sendall(live.encode_request(live.SwitchLayout(wanted)))
        try:
            reply = next(message for message in messages if isinstance(message, Reply))
        except (StopIteration, TimeoutError) as e:
            raise click.ClickException(f"the daemon did not switch to {wanted}") from e
        if not reply.ok:
            raise click.ClickException(reply.message)
        click.echo(f"Layout {wanted}")


@main.command("mumble-plugin")
@click.option(
    "--build", "rebuild", is_flag=True, help="Build the plugin from the sources (a checkout, cmake, a C compiler)."
)
@click.option("--install", is_flag=True, help="Open the plugin with Mumble's installer (built first if there is none).")
def mumble_plugin(rebuild: bool, install: bool) -> None:
    """Tell where the Mumble plugin is and whether Mumble has it, or build it and hand it to Mumble."""
    try:
        if install:
            click.echo(mumble.install(rebuild=rebuild))
            return
        if rebuild:
            click.echo(f"Built {mumble.build()}")
            return
    except mumble.MumbleError as e:
        raise click.ClickException(str(e)) from e
    found = mumble.setup()
    if found.bundle is not None:
        bundle = str(found.bundle)
    elif found.buildable:
        bundle = "none yet, --build builds it"
    else:
        bundle = "none (a release has it, a checkout builds it with cmake and a C compiler)"
    click.echo(f"Plugin: {bundle}")
    click.echo(f"Mumble: {'installed' if found.mumble else 'not found'}")
    click.echo(f"In Mumble: {found.installed or 'not installed (--install)'}")


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
    """
    List the outputs and inputs, with the names to use as `device` (* marks the defaults), and the sound cards with
    their profiles (* marks the active ones), for `card` and `profile` of `choices`.
    """
    state = _audio_state()
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
        groups = presets.matching_stream(stream.app, stream.binary)
        name += f" ({', '.join(groups)})" if groups else ""
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
@click.option(
    "--remove-override",
    is_flag=True,
    help="Only remove the unit in ~/.config/systemd/user that overrides the one of the package (enabled and running "
    "stay so).",
)
def install_service(now: bool, remove_override: bool) -> None:
    """
    Set the daemon up as a systemd user service. The release package has its unit already; any other installation
    writes one to ~/.config/systemd/user.
    """
    service = systemd.Service()
    try:
        if remove_override:
            if not systemd.overrides_packaged_unit():
                raise click.ClickException(f"{systemd.unit_path()} does not override {systemd.PACKAGED_UNIT}")
            path = service.remove_override()
            click.echo(f"Removed {path}: the service uses {systemd.PACKAGED_UNIT} now")
            return
        path = service.install(systemd.executable(), start=now)
    except systemd.ServiceError as e:
        raise click.ClickException(str(e)) from e
    if path is None:
        click.echo(f"The package installed {systemd.PACKAGED_UNIT}")
        if systemd.overrides_packaged_unit():
            click.echo(
                f"{systemd.unit_path()} overrides it: xtouch-daemon install-service --remove-override removes that"
            )
    else:
        click.echo(f"Wrote {path}")
    if not now:
        click.echo(f"Start it with: systemctl --user enable --now {systemd.UNIT_NAME}")
    click.echo("Logs: journalctl --user -u xtouch-daemon -f")


GUI_PACKAGES = ("PyQt6", "qtawesome", "qt_themes", "qtpy", "tomlkit")
GUI_MISSING = """\
the GUI needs the gui extra: on Arch Linux, install the package xtouch-daemon-gui-bin and start xtouch-daemon-gui;
from the checkout, install xtouch-daemon with the extra:
  uv tool install --force './xtouch-daemon[gui]'"""


@main.command()
@CONFIG_OPTION
def gui(config_path: Path | None) -> None:
    """Edit the configuration in a window, and apply it (needs the gui extra)."""
    try:
        from xtouch_daemon.gui.qt import run_gui
    except ImportError as e:
        if e.name is None or e.name.split(".")[0] not in GUI_PACKAGES:
            raise
        raise click.ClickException(GUI_MISSING) from e
    try:
        code = run_gui(config_path or default_config_path())
    except ConfigError as e:
        raise click.ClickException(str(e)) from e
    sys.exit(code)
