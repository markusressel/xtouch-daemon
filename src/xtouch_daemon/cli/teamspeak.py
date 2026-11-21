"""
Building and installing the TeamSpeak 3 plugin (`teamspeak-plugin`).
"""

import click

from xtouch_daemon.voip import teamspeak


@click.command("teamspeak-plugin")
@click.option(
    "--build",
    "rebuild",
    is_flag=True,
    help="Build the plugin from the sources (a checkout, cmake, a C compiler; the first build downloads its SDK).",
)
@click.option(
    "--install", is_flag=True, help="Copy the plugin into ~/.ts3client/plugins (built first if there is none)."
)
def teamspeak_plugin(rebuild: bool, install: bool) -> None:
    """Tell where the TeamSpeak plugin is and whether TeamSpeak has it, or build it and hand it to TeamSpeak."""
    try:
        if install:
            click.echo(teamspeak.install(rebuild=rebuild))
            return
        if rebuild:
            click.echo(f"Built {teamspeak.build()}")
            return
    except teamspeak.TeamSpeakError as e:
        raise click.ClickException(str(e)) from e
    found = teamspeak.setup()
    if found.library is not None:
        library = str(found.library)
    elif found.buildable:
        library = "none yet, --build builds it"
    else:
        library = "none (a release has it, a checkout builds it with cmake and a C compiler)"
    click.echo(f"Plugin: {library}")
    click.echo(f"TeamSpeak: {'installed' if found.teamspeak else 'not found'}")
    click.echo(f"In TeamSpeak: {found.installed or 'not installed (--install)'}")
