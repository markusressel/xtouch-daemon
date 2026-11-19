import pytest

from tests.support.audio import output, source, stream
from xtouch_daemon.audio.model import AudioState, Card, Direction, Profile
from xtouch_daemon.config import presets
from xtouch_daemon.config.presets import PRESETS, Preset
from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.domain.sources import (
    Suggestion,
    applications,
    card_profiles,
    cards,
    contents,
    devices,
    filtered,
    matches_text,
    patterns,
    preset_suggestions,
    preset_tip,
    profiles,
    spans,
    summary,
)
from xtouch_daemon.live.messages import KnownDevice

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
        Suggestion("speaker", "speaker description", names=("speaker description",)),
        Suggestion("buds", "buds description", origin="default", names=("buds description",)),
    )
    assert devices(STATE, Direction.INPUT) == (
        Suggestion("mic", "mic description", origin="default", names=("mic description",)),
    )


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


def test_profiles_of_the_cards_of_the_devices_with_the_active_one_marked():
    state = AudioState(
        outputs=(output("speaker", card="onboard"),),
        cards=(
            Card("onboard", "analog", (Profile("analog", "Analog Output"), Profile("digital", "Digital Output"))),
            Card("hdmi", "off", (Profile("off", "Off"),)),
        ),
    )
    assert profiles(state, Direction.OUTPUT) == (
        Suggestion("analog", "Analog Output", origin="active", names=("Analog Output",)),
        Suggestion("digital", "Digital Output", names=("Digital Output",)),
    )
    assert profiles(state, Direction.INPUT) == ()


def test_cards_and_their_profiles_for_choices():
    state = AudioState(
        outputs=(output("speaker", card="onboard"),),
        cards=(
            Card("onboard", "analog", (Profile("analog", "Analog"), Profile("digital", "Digital")), "HD Audio"),
            Card("hdmi", "off"),
        ),
    )
    assert cards(state) == (
        Suggestion("onboard", "HD Audio", tip="speaker", names=("HD Audio",)),
        Suggestion("hdmi", ""),
    )
    # without a description: by its devices
    nameless = AudioState(outputs=(output("speaker", card="onboard"),), cards=(Card("onboard", "analog"),))
    assert cards(nameless)[0].detail == "The card of speaker description"
    # by its description too
    assert card_profiles(state, "HD*") == (
        Suggestion("analog", "Analog", origin="active", names=("Analog",)),
        Suggestion("digital", "Digital", names=("Digital",)),
    )
    assert card_profiles(state, "") == card_profiles(state, "gone") == ()


def test_the_presets_of_a_kind_of_list_with_what_they_stand_for():
    suggestions = preset_suggestions(PresetKind.PROCESSES)
    assert [suggestion.value for suggestion in suggestions] == [f"@{name}" for name in PRESETS]
    steam = next(suggestion for suggestion in suggestions if suggestion.value == "@steam-games")
    assert steam.detail == "Games started from Steam"
    assert steam.tip.startswith("Games started from Steam: reaper\n\nSteam starts every game through its `reaper`")
    assert steam.preset
    assert not Suggestion("brave", "").preset
    assert preset_tip("@video", PresetKind.STREAMS) == (
        "Video players: vlc, mpv, celluloid, totem, kodi, haruna, clapper, mplayer"
    )


def test_a_tip_for_names_and_presets_that_do_not_fit(monkeypatch: pytest.MonkeyPatch):
    assert preset_tip("brave", PresetKind.STREAMS) == ""
    assert preset_tip("@nope", PresetKind.STREAMS) == ""
    monkeypatch.setattr(presets, "PRESETS", {"toys": Preset("toys", "Toys", streams=("rattle",))})
    assert preset_tip("@toys", PresetKind.PROCESSES) == "Toys: not for `processes` of states"
    assert preset_suggestions(PresetKind.PROCESSES) == ()


def test_what_the_sound_server_has_by_kind():
    assert contents(STATE) == (
        ("Outputs", (("speaker description", ""), ("buds description", "(the default)"))),
        ("Inputs", (("mic description", "(the default)"),)),
        ("Applications", (("Brave", ""), ("Game", ""), ("WEBRTC VoiceEngine", ""))),
    )


ONBOARD = "alsa_card.pci-0000_11_00.4"
DIGITAL = "alsa_output.pci-0000_11_00.4.iec958-stereo"
CARDS = AudioState(
    outputs=(output("alsa_output.pci-0000_11_00.4.analog-stereo", card=ONBOARD),),
    inputs=(source("mic"),),
    cards=(
        Card(
            ONBOARD,
            "output:analog-stereo+input:analog-stereo",
            (
                Profile("output:analog-stereo+input:analog-stereo", "Analog Stereo Duplex"),
                Profile("output:iec958-stereo+input:analog-stereo", "Digital Stereo (IEC958) Output + Analog Input"),
                Profile("output:hdmi-stereo+input:analog-stereo", "HDMI"),
                Profile("pro-audio", "Pro Audio"),
                Profile("off", "Off"),
            ),
            "HD Audio",
        ),
        # named otherwise (UCM): its devices can't be told
        Card("usb-card", "a", (Profile("output:b", "B"),)),
    ),
)


def test_the_devices_another_profile_of_a_card_would_make():
    assert devices(CARDS, Direction.OUTPUT)[1:] == (
        Suggestion(
            DIGITAL,
            "Digital Stereo (IEC958) Output (HD Audio)",
            origin="after a switch of the profile",
            card=ONBOARD,
            profile="output:iec958-stereo+input:analog-stereo",
            present=False,
        ),
        # a description without its parts names each of them
        Suggestion(
            "alsa_output.pci-0000_11_00.4.hdmi-stereo",
            "HDMI (HD Audio)",
            origin="after a switch of the profile",
            card=ONBOARD,
            profile="output:hdmi-stereo+input:analog-stereo",
            present=False,
        ),
    )
    # an input of several profiles once
    assert [(s.value, s.detail) for s in devices(CARDS, Direction.INPUT)[1:]] == [
        ("alsa_input.pci-0000_11_00.4.analog-stereo", "Analog Input (HD Audio)")
    ]


def test_the_devices_the_daemon_remembers_with_when_and_what_they_need():
    now = 10 * 86400.0
    forgotten: list[str] = []
    known = (
        KnownDevice(
            DIGITAL, "Digital Output", "output", ONBOARD, "output:iec958-stereo+input:analog-stereo", now - 2 * 86400
        ),
        KnownDevice("bluez_output.buds", "Buds Pro", "output", None, None, now - 3600),
        KnownDevice("alsa_output.pci-0000_11_00.4.pro-output-0", "Pro", "output", ONBOARD, "pro-audio", now - 86400),
        # there now, or of the other direction: not suggested again
        KnownDevice("alsa_output.pci-0000_11_00.4.analog-stereo", "Analog", "output", ONBOARD, None, now),
        KnownDevice("headset_mic", "Headset", "input", None, None, now),
    )

    found = devices(CARDS, Direction.OUTPUT, known, now, lambda device: forgotten.append(device.name))[1:]

    assert found == (
        # what the profile would make, with the description the daemon saw
        Suggestion(
            DIGITAL,
            "Digital Output",
            origin="seen 2 days ago, after a switch of the profile",
            names=("Digital Output",),
            card=ONBOARD,
            profile="output:iec958-stereo+input:analog-stereo",
            present=False,
        ),
        found[1],
        Suggestion("bluez_output.buds", "Buds Pro", origin="seen today", names=("Buds Pro",), present=False),
        # a card that is there in another profile: picked, it switches to the one that made it
        Suggestion(
            "alsa_output.pci-0000_11_00.4.pro-output-0",
            "Pro",
            origin="seen yesterday",
            names=("Pro",),
            card=ONBOARD,
            profile="pro-audio",
            present=False,
        ),
    )
    for suggestion in found:
        if suggestion.forget is not None:
            suggestion.forget()
    assert forgotten == [DIGITAL, "bluez_output.buds", "alsa_output.pci-0000_11_00.4.pro-output-0"]


SUGGESTIONS = (
    Suggestion("bluez_output.a", "WH-1000XM4", names=("WH-1000XM4",)),
    Suggestion("bluez_output.b", "Buds Pro", names=("Buds Pro",), present=False),
    Suggestion("bluez_output.c", "", names=("Speaker C",)),
    Suggestion("bluez_output.d", "Pods", names=("Pods",)),
    Suggestion("speaker", "Speaker", names=("Speaker",)),
)


def test_what_a_value_names_in_words():
    assert matches_text("Speaker", SUGGESTIONS) == ("Matches Speaker", True)
    assert matches_text("bluez_output.b", SUGGESTIONS) == ("Matches Buds Pro, not there now", True)
    assert matches_text("bluez_output.*", SUGGESTIONS) == (
        "Matches 4: WH-1000XM4, Buds Pro, not there now, bluez_output.c and 1 more (the first one that is there)",
        True,
    )
    assert matches_text("Speaker C", SUGGESTIONS) == ("Matches bluez_output.c", True)
    assert matches_text("nothing", SUGGESTIONS) == ("Matches nothing known: it may come later", False)


def test_the_suggestions_for_what_is_typed_and_where_it_matches():
    assert filtered("", SUGGESTIONS) == SUGGESTIONS
    assert [s.value for s in filtered("*.[ab]", SUGGESTIONS)] == ["bluez_output.a", "bluez_output.b"]
    assert [s.value for s in filtered("speak", SUGGESTIONS)] == ["bluez_output.c", "speaker"]
    assert spans("Bluez Output", "out") == [(6, 9)]
    assert spans("bluez_output.a", "blu*put.?") == [(0, 3), (9, 13)]
    assert spans("bluez_output.a", "x*") == []
    assert spans("anything", "") == []
