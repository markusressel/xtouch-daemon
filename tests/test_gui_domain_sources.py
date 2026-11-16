import pytest

from tests.conftest import output, source, stream
from xtouch_daemon import presets
from xtouch_daemon.audio.model import AudioState, Card, Direction, Profile
from xtouch_daemon.gui.domain.sources import (
    Suggestion,
    applications,
    card_profiles,
    cards,
    devices,
    patterns,
    preset_suggestions,
    preset_tip,
    profiles,
    summary,
)
from xtouch_daemon.presets import PRESETS, Preset
from xtouch_daemon.presets import Kind as PresetKind

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


def test_profiles_of_the_cards_of_the_devices_with_the_active_one_marked():
    state = AudioState(
        outputs=(output("speaker", card="onboard"),),
        cards=(
            Card("onboard", "analog", (Profile("analog", "Analog Output"), Profile("digital", "Digital Output"))),
            Card("hdmi", "off", (Profile("off", "Off"),)),
        ),
    )
    assert profiles(state, Direction.OUTPUT) == (
        Suggestion("analog", "Analog Output (active)"),
        Suggestion("digital", "Digital Output"),
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
    assert cards(state) == (Suggestion("onboard", "HD Audio, speaker"), Suggestion("hdmi", ""))
    # by its description too
    assert card_profiles(state, "HD*") == (Suggestion("analog", "Analog (active)"), Suggestion("digital", "Digital"))
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
    assert preset_tip("@toys", PresetKind.PROCESSES) == "Toys: not for `processes` of layouts"
    assert preset_suggestions(PresetKind.PROCESSES) == ()
