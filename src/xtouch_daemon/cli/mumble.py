"""
Building and installing the Mumble plugin (`mumble-plugin`).
"""

import click

from xtouch_daemon.voip import mumble


@click.command("mumble-plugin")
@click.option(
    "--build", "rebuild", is_flag=True, help="Build the plugin from the sources (a checkout, cmake, a C compiler)."
)
@click.option(
    "--install", is_flag=True, help="Copy the plugin into Mumble's plugin folder (built first if there is none)."
)
def mumble_plugin(rebuild: bool, install: bool) -> None:
    """Tell where the Mumble plugin is and whether Mumble has it, or build it and copy it to Mumble."""
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
