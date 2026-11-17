"""
`simulate`: what the slots of a configuration in the format of channels, states and slots show in given states (the
prototype of docs/design/channels-states-slots.md).
"""

import time
import tomllib
from pathlib import Path

import click

from xtouch_daemon.audio.pulse import SoundServerError, read_state
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.model import AUTO, DEFAULT, PEOPLE, Scene
from xtouch_daemon.slots.outcomes import outcomes, states_for, table
from xtouch_daemon.slots.recording import (
    only_watched,
    read_log,
    read_voip,
    record,
    watched_processes,
)
from xtouch_daemon.slots.replay import clock
from xtouch_daemon.slots.replay import replay as replay_log
from xtouch_daemon.slots.resolver import Inputs, resolve
from xtouch_daemon.system import instance
from xtouch_daemon.system.processes import running_processes


@click.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--mode", "mode", default=DEFAULT, show_default=True, help="The mode that is on.")
@click.option("--state", "states", multiple=True, help="A state that is on (repeat for more).")
@click.option("--absent", multiple=True, help="A channel that is not present (repeat for more).")
@click.option("--playing", multiple=True, help="An application that plays, in the order they started.")
@click.option("--person", "people", multiple=True, help="A person in the voice chat.")
@click.option("--table", "as_table", is_flag=True, help="Print the distinct outcomes of every combination instead.")
@click.option(
    "--replay",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Replay the observations of a log of `observe` instead: what the states and slots would have done.",
)
def simulate(
    file: Path,
    mode: str,
    states: tuple[str, ...],
    absent: tuple[str, ...],
    playing: tuple[str, ...],
    people: tuple[str, ...],
    as_table: bool,
    replay: Path | None,
) -> None:
    """What the 8 slots of FILE show, and why (a configuration with [channel.*], [state.*] and [slots])."""
    try:
        scene = Scene.of(tomllib.loads(file.read_text()))
    except (ConfigError, tomllib.TOMLDecodeError) as e:
        raise click.ClickException(f"{file}:\n{e}") from e
    if as_table:
        click.echo(table(outcomes(scene)))
        return
    if replay is not None:
        report = replay_log(scene, read_log(replay))
        for event in report.events:
            click.echo(f"{clock(event.at)}  {event.text}")
        click.echo()
        for line in report.summary():
            click.echo(line)
        for event in report.flaps:
            click.echo(f"flap at {clock(event.at)}: {event.text}")
        return
    if mode != DEFAULT and mode not in scene.modes:
        raise click.ClickException(f"--mode {mode}: no mode of {file} ({', '.join((DEFAULT, *scene.modes))})")
    for name in states:
        if name not in scene.states or name in scene.modes:
            hint = ", a mode goes to --mode" if name in scene.modes else ""
            raise click.ClickException(f"--state {name}: no state of {file}{hint}")
    for name in absent:
        if name not in scene.channels and (name not in scene.pools or name in (AUTO, PEOPLE)):
            hint = ", use --playing or --person" if name in (AUTO, PEOPLE) else ""
            raise click.ClickException(f"--absent {name}: no channel or pool of channels of {file}{hint}")
    values = states_for(scene, mode, states)
    gone = {
        channel
        for name in absent
        for channel in scene.members_of(scene.pools[name].channels if name in scene.pools else (name,))
    }
    present = frozenset(name for name in scene.channels if name not in gone)
    result = resolve(scene, Inputs(values, present, Observation(playing=playing, people=people)))
    for slot, shown in result.slots.items():
        click.echo(f"{slot}  {shown}")
        for line in result.why[slot][:-1]:
            click.echo(f"     {line}")
    for pool, members in result.waiting.items():
        click.echo(f"waiting for a slot of {pool}: {', '.join(members)}")


@click.command()
@click.argument("log", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--interval", default=2.0, show_default=True, help="Seconds between two looks.")
@click.option("--process", "extra", multiple=True, help="Also record processes with this in their name.")
def observe(log: Path, interval: float, extra: tuple[str, ...]) -> None:
    """
    Record what plays, records and runs (and the voice chat of the running daemon) to LOG, until Ctrl+C, for
    `simulate --replay`. A line only when something changed.
    """
    watched = watched_processes(extra)
    try:
        record(
            log,
            read_audio=lambda: read_state("xtouch-daemon-observe"),
            read_processes=lambda: only_watched(running_processes(), watched),
            read_voice=lambda: read_voip(instance.socket_file()),
            clock=time.time,
            wait=time.sleep,
            interval=interval,
        )
    except KeyboardInterrupt:
        pass
    except SoundServerError as e:
        raise click.ClickException(str(e)) from e
