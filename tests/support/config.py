"""
Helpers for the tests of the configuration.
"""

import pytest

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import parse_config


def errors_of(text: str) -> str:
    with pytest.raises(ConfigError) as error:
        parse_config(text, "config.toml")
    return str(error.value)


MQTT = '[mqtt]\nhost = "broker"\n'
