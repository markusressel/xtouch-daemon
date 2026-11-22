"""
The states: their sources, delays, overrides, modes and composed states.
"""

from tests.support.slots import scene
from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.states import Override, StateEngine

SCENE = """
[channel.spotify]
type = "apps"
match = ["spotify"]
tags = ["media"]

[state.music]
channels = ["#media"]

[state.call]
voice_chat = true
recording = ["discord"]
delay_on = 2
delay_off = 30

[state.wireless]
devices = ["bluez_output.*"]

[state.night]
homeassistant = true

[state.vpn]
command = { poll = ["/usr/local/bin/vpn-up", "--quiet"], every = 5 }

[state.manual]

[state.quiet]
when = "night and not call"

[state.calm]
when = "quiet or manual"
persist = true

[state.gaming]
mode = true
processes = ["@steam-games"]
apps = ["steam_app_"]

[state.video]
mode = true
priority = 1
apps = ["mpv"]

[state.party]
mode = true
apps = ["party"]
"""

NOTHING = Observation()


def engine(**kwargs: object) -> StateEngine:
    return StateEngine(scene(SCENE), **kwargs)  # pyright: ignore[reportArgumentType]


def test_each_source_with_the_reason():
    states = engine().update(
        Observation(
            playing=("steam_app_42",),
            recording=("Discord",),
            processes=frozenset({"reaper"}),
            devices=frozenset({"bluez_output.1"}),
            homeassistant=frozenset({"night"}),
            commands=frozenset({"vpn"}),
        ),
        frozenset({"spotify"}),
        0,
    )
    on = {name for name, value in states.values.items() if value}
    assert on == {"music", "call", "wireless", "night", "vpn", "gaming"}
    assert states.mode == "gaming"
    assert states.reasons["call"] == "Discord records"
    assert states.reasons["music"] == "spotify is present"
    assert states.reasons["wireless"] == "bluez_output.1 is there"
    assert states.reasons["night"] == "Home Assistant"
    # the program by its name, without its folder and arguments
    assert states.reasons["vpn"] == "vpn-up says on"
    assert states.reasons["gaming"] == "steam_app_42 plays"
    assert states.reasons["quiet"] == ""
    assert engine().update(Observation(voice_chat=True), frozenset(), 0).reasons["call"] == "in a voice chat"
    assert not engine().update(Observation(devices=frozenset({"alsa_output.x"})), frozenset(), 0).values["wireless"]
    assert engine().update(Observation(processes=frozenset({"reaper"})), frozenset(), 0).reasons["gaming"] == (
        "reaper runs"
    )


def test_delays_swallow_a_join_tone_and_a_dropped_call():
    states = engine()
    states.update(NOTHING, frozenset(), 0)
    assert not states.update(Observation(voice_chat=True), frozenset(), 10).values["call"]
    assert states.deadline() == 12
    assert not states.update(NOTHING, frozenset(), 11).values["call"]
    states.update(Observation(voice_chat=True), frozenset(), 20)
    result = states.update(Observation(voice_chat=True), frozenset(), 22)
    assert result.values["call"]
    assert result.since["call"] == 22
    assert states.update(NOTHING, frozenset(), 40).values["call"]
    assert not states.update(NOTHING, frozenset(), 70).values["call"]


def test_the_first_update_is_the_baseline_without_delays():
    assert engine().update(Observation(voice_chat=True), frozenset(), 0).values["call"]


def test_an_override_takes_effect_at_once_and_ends_at_the_next_edge():
    states = engine()
    states.update(NOTHING, frozenset(), 0)
    states.set_override("call", Override.ON)
    assert states.update(NOTHING, frozenset(), 1).values["call"]
    assert states.update(NOTHING, frozenset(), 1).reasons["call"] == "override"
    states.set_override("call", Override.AUTO)
    assert not states.update(NOTHING, frozenset(), 2).values["call"]
    states.set_override("call", Override.OFF)
    states.update(Observation(voice_chat=True), frozenset(), 3)
    assert not states.update(Observation(voice_chat=True), frozenset(), 4).values["call"]
    # the sources turned on (after their delay): auto again, and they decide
    assert states.update(Observation(voice_chat=True), frozenset(), 5).values["call"]
    assert "call" not in states.overrides


def test_kept_overrides_survive_the_baseline_and_states_without_sources_keep_theirs():
    states = engine(overrides={"call": Override.ON, "manual": Override.ON, "night": Override.AUTO})
    assert states.overrides == {"call": Override.ON, "manual": Override.ON}
    first = states.update(NOTHING, frozenset(), 0)
    assert first.values["call"]
    assert first.values["manual"]
    assert first.values["calm"]
    assert states.update(NOTHING, frozenset(), 100).values["manual"]


def test_composed_states_follow_and_can_be_overridden():
    states = engine()
    assert states.update(Observation(homeassistant=frozenset({"night"})), frozenset(), 0).values["quiet"]
    result = states.update(Observation(homeassistant=frozenset({"night"}), voice_chat=True), frozenset(), 10)
    assert result.values["quiet"]  # call is not on yet
    states.update(Observation(homeassistant=frozenset({"night"}), voice_chat=True), frozenset(), 12)
    result = states.update(Observation(homeassistant=frozenset({"night"}), voice_chat=True), frozenset(), 15)
    assert not result.values["quiet"]
    assert result.reasons["quiet"] == ""
    states.set_override("quiet", Override.ON)
    result = states.update(Observation(homeassistant=frozenset({"night"}), voice_chat=True), frozenset(), 16)
    assert result.values["quiet"]
    assert result.reasons["quiet"] == "override"
    assert result.reasons["calm"] == "quiet or manual"
    # an edge of the composed state ends its override, not one of a state with persist
    states.set_override("calm", Override.OFF)
    states.update(Observation(homeassistant=frozenset({"night"})), frozenset(), 50)
    # the call ends after its delay_off: quiet turns on by itself
    result = states.update(Observation(homeassistant=frozenset({"night"})), frozenset(), 80)
    assert "quiet" not in states.overrides
    assert states.overrides["calm"] is Override.OFF
    assert not result.values["calm"]


def test_the_mode_by_priority_then_the_order_of_the_file():
    states = engine()
    result = states.update(Observation(playing=("steam_app_1", "party", "mpv")), frozenset(), 0)
    assert result.mode == "video"
    assert [name for name in ("default", "gaming", "video", "party") if result.values[name]] == ["video"]
    assert engine().update(Observation(playing=("party", "steam_app_1")), frozenset(), 0).mode == "gaming"
    assert engine().update(NOTHING, frozenset(), 0).values["default"]


def test_a_picked_mode_lasts_until_a_rule_starts_or_stops_matching():
    states = engine(mode_pick="party")
    first = states.update(NOTHING, frozenset(), 0)
    assert first.mode == "party"
    assert first.reasons["party"] == "picked"
    states.pick_mode("default")
    assert states.update(NOTHING, frozenset(), 1).reasons["default"] == "picked"
    assert states.update(Observation(playing=("mpv",)), frozenset(), 2).mode == "video"  # a rule started
    assert states.mode_pick is None
    states.pick_mode("gaming")
    assert states.update(Observation(playing=("mpv",)), frozenset(), 3).mode == "gaming"
    # mpv stops: after the delay_off of modes the rule stops matching, and the pick ends
    assert states.update(NOTHING, frozenset(), 4).mode == "gaming"
    assert states.update(NOTHING, frozenset(), 14).mode == "default"
    states.pick_mode("party")
    states.pick_mode(None)
    assert states.update(NOTHING, frozenset(), 15).mode == "default"


def test_a_pick_lasts_while_the_rules_want_the_same_mode_and_through_modes_with_persist():
    states = StateEngine(scene(SCENE.replace('apps = ["steam_app_"]', 'apps = ["steam_app_"]\npersist = true')))
    states.update(Observation(playing=("mpv",)), frozenset(), 0)
    states.pick_mode("default")
    # party starts, but video still wins: the rules want the same mode
    assert states.update(Observation(playing=("mpv", "party")), frozenset(), 1).mode == "default"
    # gaming has persist: its start doesn't end the pick, though it wins now
    assert states.update(Observation(playing=("mpv", "steam_app_1")), frozenset(), 2).mode == "default"
    # video stops: the rules want gaming, a change by a mode without persist
    assert states.update(Observation(playing=("steam_app_1",)), frozenset(), 3).mode == "default"
    assert states.update(Observation(playing=("steam_app_1",)), frozenset(), 13).mode == "gaming"


def test_composed_states_have_no_delays_of_their_own():
    """quiet is "night and not call": it turns on the moment call is off, the two never overlap."""
    states = engine()
    states.update(Observation(homeassistant=frozenset({"night"})), frozenset(), 0)
    calling = Observation(homeassistant=frozenset({"night"}), voice_chat=True)
    states.update(calling, frozenset(), 1)
    result = states.update(calling, frozenset(), 3)
    assert (result.values["call"], result.values["quiet"]) == (True, False)
    states.update(Observation(homeassistant=frozenset({"night"})), frozenset(), 33)
    result = states.update(Observation(homeassistant=frozenset({"night"})), frozenset(), 62.9)
    assert (result.values["call"], result.values["quiet"]) == (True, False)
    result = states.update(Observation(homeassistant=frozenset({"night"})), frozenset(), 63)
    assert (result.values["call"], result.values["quiet"]) == (False, True)
