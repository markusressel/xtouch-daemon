from pathlib import Path

import pytest

from tests.conftest import stream
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import Config, parse_config
from xtouch_daemon.layouts import LayoutSwitcher, rule_match, running_processes

LAYOUTS = """
[switching]
hold = 10

[[layout]]
name = "gaming"
label = "Gaming"
apps = ["steam_app_"]

[[layout]]
name = "voice"
processes = ["mumble"]

[[layout]]
name = "music"
apps = ["spotify"]
priority = 5

[[layout]]
name = "plain"
"""

GAME = AudioState(streams=(stream(1, "steam_app_42", "wine"),))
MUSIC = AudioState(streams=(stream(2, "Spotify", "spotify"),))
BOTH = AudioState(streams=(*GAME.streams, *MUSIC.streams))
QUIET = AudioState()


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def config() -> Config:
    return parse_config(LAYOUTS)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def switches() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def switcher(config: Config, clock: Clock, switches: list[tuple[str, str]]) -> LayoutSwitcher:
    return LayoutSwitcher(config, lambda name, reason: switches.append((name, reason)), clock=clock)


def test_running_processes_are_the_names_and_programs_of_proc(tmp_path: Path):
    for pid, comm, cmdline in (
        ("12", "mumble\n", b"/usr/bin/mumble\0--multiple\0"),
        ("13", "Web Content\n", b"/usr/lib/firefox/firefox\0-contentproc\0"),
        # kernel threads have no command line: "oom_reaper" must not match a rule for Steam's "reaper"
        ("14", "oom_reaper\n", b""),
        ("17", "reaper\n", b"/home/me/.local/share/Steam/ubuntu12_32/reaper\0SteamLaunch\0"),
    ):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "comm").write_text(comm)
        (tmp_path / pid / "cmdline").write_bytes(cmdline)
    # gone in the meantime, and no process at all
    (tmp_path / "15").mkdir()
    (tmp_path / "self").mkdir()
    (tmp_path / "16").mkdir()
    (tmp_path / "16" / "comm").write_text("\n")
    (tmp_path / "16" / "cmdline").write_bytes(b"")
    assert running_processes(tmp_path) == {"mumble", "web content", "firefox", "reaper"}


@pytest.mark.host
def test_running_processes_of_this_machine_include_this_one():
    assert running_processes(Path("/proc"))


def test_a_rule_matches_an_application_with_a_stream_or_a_process(config: Config):
    gaming, voice, music, plain = config.layouts
    assert rule_match(gaming, GAME, ()) == "steam_app_42"
    assert rule_match(gaming, AudioState(streams=(stream(1, "", "steam_app_7"),)), ()) == "steam_app_7"
    assert rule_match(gaming, MUSIC, ()) is None
    assert rule_match(voice, QUIET, {"bash", "mumble"}) == "mumble"
    assert rule_match(voice, QUIET, {"bash"}) is None
    assert rule_match(music, QUIET, {"spotify"}) is None
    assert rule_match(plain, BOTH, {"mumble"}) is None


def test_switching_by_hand(switcher: LayoutSwitcher, switches: list[tuple[str, str]]):
    assert switcher.active == "default"
    assert switcher.names == ("default", "gaming", "voice", "music", "plain")
    assert switcher.switch("gaming")
    assert not switcher.switch("gaming")
    assert switcher.step(1, "buttons")
    assert switcher.step(-1)
    assert switcher.step(-1)
    assert switcher.step(-1)
    assert switches == [("gaming", "manual"), ("voice", "buttons"), ("gaming", "manual"), ("default", "manual"),
                        ("plain", "manual")]  # fmt: skip
    with pytest.raises(KeyError):
        switcher.switch("nope")


def test_the_active_layout_of_a_new_switcher(config: Config):
    assert LayoutSwitcher(config, lambda *_: None, active="music").active == "music"
    assert LayoutSwitcher(config, lambda *_: None, active="removed").active == "default"


def test_which_rules_there_are(config: Config, switcher: LayoutSwitcher):
    assert switcher.has_rules
    assert switcher.watches_processes
    plain = LayoutSwitcher(parse_config('[[layout]]\nname = "x"\napps = ["a"]\n'), lambda *_: None)
    assert plain.has_rules
    assert not plain.watches_processes
    assert not LayoutSwitcher(parse_config(""), lambda *_: None).has_rules


def test_a_rule_switches_when_it_starts_and_stops_matching(
    switcher: LayoutSwitcher, switches: list[tuple[str, str]], clock: Clock
):
    switcher.evaluate(QUIET)
    assert switches == []
    switcher.evaluate(GAME)
    assert switches == [("gaming", "steam_app_42")]
    switcher.evaluate(GAME)
    # the game ended: its layout stays for the hold time
    clock.now += 10
    switcher.evaluate(QUIET)
    assert switcher.active == "gaming"
    clock.now += 1
    switcher.evaluate(QUIET)
    assert switches[-1] == ("default", "")


def test_the_highest_priority_wins_then_the_first(switcher: LayoutSwitcher, switches: list[tuple[str, str]]):
    switcher.evaluate(BOTH, {"mumble"})
    assert switches == [("music", "Spotify")]
    switcher.evaluate(GAME, {"mumble"})
    # music holds on
    assert switcher.active == "music"


def test_a_tie_goes_to_the_first_layout(switcher: LayoutSwitcher, switches: list[tuple[str, str]]):
    # gaming and voice have the same priority
    switcher.evaluate(GAME, {"mumble"})
    assert switches == [("gaming", "steam_app_42")]


def test_a_layout_chosen_by_hand_stays_until_the_rules_change(
    switcher: LayoutSwitcher, switches: list[tuple[str, str]], clock: Clock
):
    switcher.evaluate(GAME)
    switcher.switch("plain")
    switcher.evaluate(GAME)
    assert switcher.active == "plain"
    clock.now += 11
    switcher.evaluate(QUIET)
    # the rules want the default again: something happened
    assert switcher.active == "default"
    assert switches == [("gaming", "steam_app_42"), ("plain", "manual"), ("default", "")]


def test_without_hold_a_layout_goes_at_once(clock: Clock, switches: list[tuple[str, str]]):
    config = parse_config('[switching]\nhold = 0\n[[layout]]\nname = "gaming"\napps = ["steam_app_"]\n')
    switcher = LayoutSwitcher(config, lambda name, reason: switches.append((name, reason)), clock=clock)
    switcher.evaluate(GAME)
    clock.now += 0.1
    switcher.evaluate(QUIET)
    assert switches == [("gaming", "steam_app_42"), ("default", "")]
