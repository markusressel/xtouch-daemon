"""
Helpers for the tests of the configuration.
"""

import pytest

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import parse_config

FULL = """
[device]
name = "X-Touch-Ext"

[behavior]
max_volume = 120
encoder_step = 2
reset_volume = 80
meters = false
auto_hold = 2.5
ignore = ["speech-dispatcher", "notify"]

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
device = "alsa_output.analog"
label = "Speaker"
color = "cyan"
select = false

[[strip]]
type = "input"

[[strip]]
type = "apps"
match = ["discord", "mumble"]
label = "VoIP"
color = "off"
meter = false

[[strip]]
type = "empty"
"""


def errors_of(text: str) -> str:
    with pytest.raises(ConfigError) as error:
        parse_config(text, "config.toml")
    return str(error.value)


HOME_ASSISTANT = '[[strip]]\ntype = "homeassistant"\n'


MQTT = '[mqtt]\nhost = "broker"\n'


GAMING = """
[[strip]]
type = "output"
label = "Speaker"

[[strip]]
type = "apps"
match = ["firefox"]
label = "Web"

[voip]
provider = "demo"

[[layout]]
name = "gaming"
label = "Gaming"
apps = ["steam_app_"]
processes = ["mumble"]
priority = 2

[[layout.strip]]
type = "inherit"

[[layout.strip]]
type = "voip"
talking_color = "yellow"

[[layout.strip]]
type = "voip"
person = ["Alice", "alice-phone"]

[[layout.strip]]
type = "voip"

[[layout.strip]]
type = "inherit"
"""
