"""
The command line: running the daemon, and the tools around it (configuration, devices, applications, a test). Each
module has the commands of one topic; `main` puts them together.
"""

import click

from xtouch_daemon import __version__
from xtouch_daemon.cli.configuration import check_config, init_config
from xtouch_daemon.cli.daemon import run, test
from xtouch_daemon.cli.editor import gui
from xtouch_daemon.cli.layouts import layout
from xtouch_daemon.cli.mumble import mumble_plugin
from xtouch_daemon.cli.service import install_service
from xtouch_daemon.cli.simulate import simulate
from xtouch_daemon.cli.sound import list_apps, list_devices


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="xtouch-daemon")
def main() -> None:
    """Use a Behringer X-Touch Extender as a hardware mixer for PipeWire."""


for command in (
    check_config,
    gui,
    init_config,
    install_service,
    layout,
    list_apps,
    list_devices,
    mumble_plugin,
    run,
    simulate,
    test,
):
    main.add_command(command)
