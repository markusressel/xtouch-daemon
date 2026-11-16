import re

import pytest

from tests.support.paths import DOCS
from xtouch_daemon.config import presets
from xtouch_daemon.config.presets import PRESETS, Kind, Preset

STREAMS_ONLY = {
    "toys": Preset("toys", "Toys", streams=("rattle",)),
    "daemons": Preset("daemons", "Daemons", processes=("systemd",)),
}
"""Presets for one kind of list each, which the real ones don't have."""

PAGE = DOCS / "configuration" / "presets.md"


def test_a_preset_stands_for_its_names_and_plain_names_stay():
    assert presets.expand(("kodi", "@video", "vlc"), Kind.STREAMS) == (
        "kodi",
        "vlc",
        "mpv",
        "celluloid",
        "totem",
        "haruna",
        "clapper",
        "mplayer",
    )


def test_a_preset_stands_for_other_names_in_lists_of_processes():
    assert presets.expand(("@steam-games",), Kind.STREAMS) == (
        "steam_app_",
        ".exe",
        "wine-preloader",
        "wine64-preloader",
    )
    assert presets.expand(("@steam-games", "@games"), Kind.PROCESSES) == ("reaper", "wineserver")


def test_an_unknown_preset_lists_the_known_ones():
    with pytest.raises(ValueError, match=r"^@browser is no preset; the presets are @browsers, @voip, @steam-games, "):
        presets.expand(("@browser",), Kind.STREAMS)


def test_a_preset_in_a_list_it_is_not_for_says_where_it_can_be_used():
    with pytest.raises(ValueError, match=re.escape("@toys is not for `processes` of layouts; use it in `match` of ")):
        presets.expand(("@toys",), Kind.PROCESSES, STREAMS_ONLY)
    with pytest.raises(
        ValueError, match=re.escape("@daemons is not for `match` of apps strips, `apps` of layouts and")
    ):
        presets.expand(("@daemons",), Kind.STREAMS, STREAMS_ONLY)


def test_the_processes_of_a_list_of_streams_leave_out_what_has_none():
    assert presets.expand_known(("@toys", "@daemons", "@nope", "plain"), Kind.PROCESSES, STREAMS_ONLY) == (
        "systemd",
        "plain",
    )


def test_describe_tells_what_presets_stand_for():
    assert presets.describe(("@steam-games", "steam", "@nope"), Kind.PROCESSES) == "@steam-games (reaper), steam, @nope"
    assert presets.describe(("@daemons",), Kind.STREAMS) == "@daemons"


def test_the_presets_of_an_application():
    assert presets.matching_stream("Brave", "brave") == ("@browsers",)
    assert presets.matching_stream("Planet Crafter.exe", "wine64-preloader") == ("@steam-games", "@games")
    assert presets.matching_stream("WEBRTC VoiceEngine", "") == ("@voip",)
    assert presets.matching_stream("speech-dispatcher-espeak", "") == ()


def test_every_preset_is_for_some_list_and_has_a_description():
    for name, preset in PRESETS.items():
        assert name == preset.name
        assert re.fullmatch(r"[a-z][a-z-]*", name)
        assert preset.kinds
        assert preset.description
        assert preset.entry == f"@{name}"


@pytest.mark.parametrize(
    ("name", "kind", "never"),
    [
        # every Wine program has a `.exe`, Steam itself is `steam`: none of these is a game
        ("steam-games", Kind.PROCESSES, ["steam", "steam.exe", "steamwebhelper", "explorer.exe", "wineserver"]),
        ("games", Kind.PROCESSES, ["steam", "steam.exe", "steamwebhelper", "explorer.exe", "services.exe"]),
        ("steam-games", Kind.STREAMS, ["Steam", "steamwebhelper"]),
        # the crash handler of every Electron application, e.g. Discord's
        ("browsers", Kind.PROCESSES, ["chrome_crashpad_handler", "chrome_crashpad", "Discord", "electron"]),
        ("browsers", Kind.STREAMS, ["Discord", "electron", "Spotify"]),
        # elementary OS applications
        ("voip", Kind.PROCESSES, ["io.elementary.music", "io.elementary.f"]),
        ("music", Kind.STREAMS, ["Firefox", "Brave", "mpv"]),
        ("video", Kind.STREAMS, ["Firefox", "Spotify"]),
    ],
)
def test_presets_leave_out_what_is_not_theirs(name: str, kind: Kind, never: list[str]):
    names = PRESETS[name].names(kind)
    assert names is not None
    for value in never:
        assert not any(part in value.lower() for part in names), value


@pytest.mark.parametrize(
    ("name", "kind", "value"),
    [
        # seen on a real machine: Planet Crafter under Proton, started from Steam
        ("steam-games", Kind.STREAMS, "Planet Crafter.exe"),
        ("steam-games", Kind.STREAMS, "wine64-preloader"),
        ("steam-games", Kind.PROCESSES, "reaper"),
        ("browsers", Kind.STREAMS, "Brave"),
        ("browsers", Kind.STREAMS, "Google Chrome"),
        ("browsers", Kind.PROCESSES, "firefox-bin"),
        ("browsers", Kind.PROCESSES, "vivaldi-bin"),
        ("voip", Kind.STREAMS, "WEBRTC VoiceEngine"),
        ("voip", Kind.STREAMS, "ZOOM VoiceEngine"),
        ("voip", Kind.PROCESSES, "ts3client_linux_amd64"),
        ("music", Kind.STREAMS, "Music Player Daemon"),
        ("video", Kind.PROCESSES, "kodi.bin"),
        ("video", Kind.PROCESSES, "smplayer"),
    ],
)
def test_presets_match_their_applications(name: str, kind: Kind, value: str):
    names = PRESETS[name].names(kind)
    assert names is not None
    assert any(part in value.lower() for part in names)


def test_the_page_of_the_presets_has_the_table_of_the_code():
    text = PAGE.read_text(encoding="utf-8")
    start, end = "<!-- presets: start -->\n", "\n<!-- presets: end -->"
    assert text[text.index(start) + len(start) : text.index(end)] == presets.markdown_table()


def test_a_preset_for_one_kind_has_no_names_for_the_other_in_the_table(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(presets, "PRESETS", STREAMS_ONLY)
    assert presets.markdown_table().splitlines()[2:] == [
        "| `@toys` | Toys | `rattle` | - |",
        "| `@daemons` | Daemons | - | `systemd` |",
    ]
