from tests.conftest import output, source, stream
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.gui.domain.sources import Suggestion, applications, devices, patterns, summary

STATE = AudioState(
    outputs=(output("speaker"), output("buds")),
    inputs=(source("mic"),),
    streams=(
        stream(1, "Brave", "brave"),
        stream(2, "Brave", "brave"),
        stream(3, "WEBRTC VoiceEngine", "Discord"),
        stream(4, "Game", ""),
    ),
    default_output="buds",
    default_input="mic",
)


def test_devices_by_node_name_with_the_default_marked():
    assert devices(STATE, Direction.OUTPUT) == (
        Suggestion("speaker", "speaker description"),
        Suggestion("buds", "buds description (the default)"),
    )
    assert devices(STATE, Direction.INPUT) == (Suggestion("mic", "mic description (the default)"),)


def test_applications_once_each_with_their_binaries():
    assert applications(STATE) == (
        Suggestion("Brave", "brave"),
        Suggestion("WEBRTC VoiceEngine", "Discord"),
        Suggestion("Game", ""),
    )


def test_patterns_are_binaries_and_names():
    assert patterns(STATE) == (
        Suggestion("brave", "the binary of Brave"),
        Suggestion("Brave", "an application"),
        Suggestion("Discord", "the binary of WEBRTC VoiceEngine"),
        Suggestion("WEBRTC VoiceEngine", "an application"),
        Suggestion("Game", "an application"),
    )


def test_the_summary_counts():
    assert summary(STATE) == "2 outputs, 1 input, 3 applications"
    assert summary(AudioState(streams=(stream(1),))) == "0 outputs, 0 inputs, 1 application"
