from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Device, Direction, Stream


def output(name: str, description: str = "", running: bool = False) -> Device:
    return Device(name, description or name, Direction.OUTPUT, 50, False, running)


def stream(index: int, app: str, binary: str = "", corked: bool = False) -> Stream:
    return Stream(index, app, binary, 80, False, corked)


SPEAKER = output("alsa_output.analog", "Analog Stereo")
BUDS = output("bluez_output.buds", "Fairbuds 2", running=True)
MIC = Device("alsa_input.analog", "Analog Stereo", Direction.INPUT, 100, False, False)

STATE = AudioState(
    outputs=(SPEAKER, BUDS),
    inputs=(MIC,),
    streams=(stream(1, "Brave", "brave"), stream(2, "WEBRTC VoiceEngine", "Discord", corked=True), stream(3, "Brave")),
    default_output="bluez_output.buds",
    default_input="alsa_input.analog",
)


def test_finds_devices_by_name_or_description():
    assert STATE.device(Direction.OUTPUT, "alsa_output.analog") is SPEAKER
    assert STATE.device(Direction.OUTPUT, "Fairbuds 2") is BUDS
    assert STATE.device(Direction.INPUT, "Analog Stereo") is MIC
    assert STATE.device(Direction.OUTPUT, "nothing") is None


def test_no_name_is_the_default_device():
    assert STATE.device(Direction.OUTPUT, None) is BUDS
    assert STATE.device(Direction.INPUT, None) is MIC
    assert AudioState(outputs=(SPEAKER,)).device(Direction.OUTPUT, None) is None


def test_knows_the_defaults():
    assert STATE.is_default(BUDS)
    assert not STATE.is_default(SPEAKER)
    assert STATE.is_default(MIC)
    assert STATE.devices(Direction.OUTPUT) == (SPEAKER, BUDS)
    assert STATE.devices(Direction.INPUT) == (MIC,)
    assert STATE.default_name(Direction.INPUT) == "alsa_input.analog"


def test_streams_match_their_application_name_or_binary_ignoring_case():
    assert [s.index for s in STATE.streams_matching(("BRAVE",))] == [1, 3]
    assert [s.index for s in STATE.streams_matching(("discord",))] == [2]
    assert [s.index for s in STATE.streams_matching(("voiceengine", "nothing"))] == [2]
    assert STATE.streams_matching(("firefox",)) == ()
    assert [s.index for s in STATE.streams_of_app("Brave")] == [1, 3]


def test_a_stream_without_a_binary_matches_by_its_name_only():
    assert not stream(4, "Brave").matches(())
    assert stream(4, "Brave").matches(("rav",))


def test_a_corked_stream_does_not_play():
    assert STATE.streams[0].playing
    assert not STATE.streams[1].playing


def test_the_disconnected_state_is_empty():
    assert not DISCONNECTED.connected
    assert DISCONNECTED.device(Direction.OUTPUT, None) is None
    assert DISCONNECTED.streams == ()
    assert STATE.connected
