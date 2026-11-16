"""
`simulate`: what the slots of a configuration in the format of channels, states and slots show in given states (the
prototype of docs/design/channels-states-slots.md).
"""

import tomllib
from pathlib import Path

import click

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.model import DEFAULT, Scene
from xtouch_daemon.slots.outcomes import outcomes, states_for, table
from xtouch_daemon.slots.resolver import Inputs, resolve


@click.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--mode", "mode", default=DEFAULT, show_default=True, help="The mode that is on.")
@click.option("--state", "states", multiple=True, help="A state that is on (repeat for more).")
@click.option("--absent", multiple=True, help="A channel that is not present (repeat for more).")
@click.option("--playing", multiple=True, help="An application that plays, in the order they started.")
@click.option("--person", "people", multiple=True, help="A person in the voice chat.")
@click.option("--table", "as_table", is_flag=True, help="Print the distinct outcomes of every combination instead.")
def simulate(
    file: Path,
    mode: str,
    states: tuple[str, ...],
    absent: tuple[str, ...],
    playing: tuple[str, ...],
    people: tuple[str, ...],
    as_table: bool,
) -> None:
    """What the 8 slots of FILE show, and why (a configuration with [channel.*], [state.*] and [slots])."""
    try:
        scene = Scene.of(tomllib.loads(file.read_text()))
    except (ConfigError, tomllib.TOMLDecodeError) as e:
        raise click.ClickException(f"{file}:\n{e}") from e
    if as_table:
        click.echo(table(outcomes(scene)))
        return
    for name in (mode, *states, *absent):
        if name != DEFAULT and name not in scene.states and name not in scene.channels:
            raise click.ClickException(f"{name} is no mode, state or channel of {file}")
    values = states_for(scene, mode, states)
    present = frozenset(name for name in scene.channels if name not in absent)
    result = resolve(scene, Inputs(values, present, Observation(playing=playing, people=people)))
    for slot, shown in result.slots.items():
        click.echo(f"{slot}  {shown}")
        for line in result.why[slot][:-1]:
            click.echo(f"     {line}")
    for pool, members in result.waiting.items():
        click.echo(f"waiting for a slot of {pool}: {', '.join(members)}")
