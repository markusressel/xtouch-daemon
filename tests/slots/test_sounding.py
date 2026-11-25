from tests.support.audio import output, source, stream
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.slots.sounding import sounding

CONFIG = """
[channel.out]
type = "output"

[channel.buds]
type = "output"
device = "bluez_output.*"

[channel.mic]
type = "input"
device = "mic description"

[channel.game]
type = "apps"
match = ["mygame"]
label = "Game"

[channel.ann]
type = "person"
person = "Ann"

[channel.knob]
type = "custom"

[slots]
1 = "out"
"""


def test_a_channel_has_sound_while_sound_flows_through_what_it_controls():
    scene = parse_config(CONFIG, "test").slots.scene
    quiet = AudioState(
        outputs=(output("speaker"), output("bluez_output.buds")),
        inputs=(source("mic"),),
        # paused by the game
        streams=(stream(1, "MyGame", "mygame", corked=True),),
        default_output="speaker",
    )
    assert sounding(scene, quiet, ()) == ()

    playing = AudioState(
        # the default output, without `device`; a pattern takes the headphones
        outputs=(output("speaker", running=True), output("bluez_output.buds", running=True)),
        # by its description
        inputs=(source("mic", running=True),),
        streams=(stream(1, "MyGame", "mygame"), stream(2, "Brave", "brave")),
        default_output="speaker",
    )
    # someone talks, the name in any case; a custom channel has no sound
    assert sounding(scene, playing, ("ANN",)) == ("out", "buds", "mic", "game", "ann")
    # without a default output the channel without `device` has nothing
    assert "out" not in sounding(scene, AudioState(outputs=(output("speaker", running=True),)), ())
