"""
The GUI, the editor of the configuration (`gui`), which needs the extra `gui`.
"""

import sys
from pathlib import Path

import click

from xtouch_daemon.cli.options import CONFIG_OPTION
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import default_config_path

GUI_PACKAGES = ("PyQt6", "qtawesome", "qt_themes", "qtpy", "tomlkit")
GUI_MISSING = """\
the GUI needs the gui extra: on Arch Linux, install the package xtouch-daemon-gui-bin and start xtouch-daemon-gui;
from the checkout, install xtouch-daemon with the extra:
  uv tool install --force './xtouch-daemon[gui]'"""


@click.command()
@CONFIG_OPTION
def gui(config_path: Path | None) -> None:
    """Edit the configuration in a window, and apply it (needs the gui extra)."""
    try:
        from xtouch_daemon.gui.quick.app import run_quick
    except ImportError as e:
        if e.name is None or e.name.split(".")[0] not in GUI_PACKAGES:
            raise
        raise click.ClickException(GUI_MISSING) from e
    try:
        code = run_quick(config_path or default_config_path())
    except ConfigError as e:
        raise click.ClickException(str(e)) from e
    sys.exit(code)
