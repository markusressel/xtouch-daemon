from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Capture, Card, Device, Direction, Stream


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


def capture(app: str, device: str | None, direction: Direction | None, corked: bool = False) -> Capture:
    return Capture(1, app, app.lower(), device, direction, corked)


def test_a_device_is_recorded_while_an_application_records_it() -> None:
    mic = Device("mic", "Mic", Direction.INPUT, 50, False, True)
    speaker = Device("speaker", "Speaker", Direction.OUTPUT, 50, False, True)
    # the monitor of the speaker is not the input of the same name
    mic_named_like_the_output = Device("speaker", "", Direction.INPUT, 50, False, True)
    state = AudioState(captures=(capture("OBS", "speaker", Direction.OUTPUT), capture("Discord", "mic", None)))

    assert state.is_recorded(speaker)
    assert not state.is_recorded(mic)
    assert not state.is_recorded(mic_named_like_the_output)
    assert not AudioState(captures=(capture("OBS", "speaker", Direction.OUTPUT, corked=True),)).is_recorded(speaker)


def test_applications_record_while_they_have_a_running_capture() -> None:
    state = AudioState(captures=(capture("Discord", "mic", Direction.INPUT), capture("OBS", None, None, corked=True)))

    assert state.records_matching(("disc",))
    assert not state.records_matching(("obs",))
    assert state.records_app("Discord")
    assert not state.records_app("OBS")
    assert not state.records_app("Disc")


def test_a_card_by_its_name_or_description() -> None:
    card = Card("alsa_card.pci-0000_11_00.4", "off", description="Family 17h/19h HD Audio Controller")
    state = AudioState(cards=(Card("usb", "off"), card))
    assert state.card_matching("alsa_card.pci-0000_11_00.4") is card
    assert state.card_matching("Family 17h*") is card
    assert state.card_matching("alsa_card.*") is card
    assert state.card_matching("Family") is None
    # without a description only by its name
    assert Card("usb", "off").matches("us?")
    assert not Card("usb", "off").matches("")
