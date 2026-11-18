"""
What the commands share: the option for the configuration file, and reading it.
"""

from pathlib import Path

import click

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import default_config_path, load_config
from xtouch_daemon.config.model import Config

CONFIG_OPTION = click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help=f"The configuration file [default: {default_config_path()}]",
)


def load_or_fail(config_path: Path | None) -> Config:
    try:
        return load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e
