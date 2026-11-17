"""
Helpers for the tests of the command line: running a command, the sound server it reads.
"""

from click.testing import CliRunner, Result

from tests.support.audio import output, source, stream
from xtouch_daemon import cli
from xtouch_daemon.audio.model import AudioState, Card, Profile

CONFIG = """
[aliases]
"WEBRTC VoiceEngine" = "Discord"

[channel.out]
type = "output"
label = "Out"

[channel.mic]
type = "input"
device = "mic"
select = false
meter = false
rec = "off"
solo = "muted"

[channel.browser]
type = "apps"
label = "Browser"
match = ["brave", "firefox"]
color = "yellow"

[channel.lights]
type = "homeassistant"
label = "Lights"

[channel.desk]
type = "homeassistant"
color = "blue"

[slots]
1 = "out"
2 = "mic"
3 = "browser"
4 = "-"
5 = "lights"
6 = "desk"

[mqtt]
host = "broker"
"""


STATE = AudioState(
    outputs=(output("speaker", 50, running=True, card="alsa_card.pci"), output("buds", 30, muted=True)),
    inputs=(source("mic", 80),),
    streams=(
        stream(1, "Brave"),
        stream(2, "WEBRTC VoiceEngine", "Discord", volume=60, corked=True),
        stream(3, "speech-dispatcher-espeak", ""),
    ),
    default_output="speaker",
    default_input="mic",
    cards=(
        Card(
            "alsa_card.pci",
            "output:analog-stereo",
            (Profile("output:analog-stereo", "Analog Stereo Output"), Profile("off", "Off")),
            "Family 17h/19h HD Audio Controller",
        ),
        Card("bluez_card.buds", "a2dp-sink", (Profile("a2dp-sink", "High Fidelity Playback"),)),
    ),
)


def invoke(*args: str) -> Result:
    return CliRunner().invoke(cli.main, list(args), catch_exceptions=False)
