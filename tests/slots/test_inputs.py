"""
The delays, and the presence of channels and pools in an observation.
"""

from tests.support.slots import attendees, scene
from xtouch_daemon.slots.inputs import Observation, Presence, excluded, owner_of, pool_present, present_now
from xtouch_daemon.slots.timing import Delayed

SCENE = """
[channel.out]
type = "output"

[channel.buds]
type = "output"
device = "bluez_output.*"
absent_after = 1

[channel.mic]
type = "input"
choices = [{ device = "alsa_input.mic" }, { device = "usb_mic" }]

[channel.browser]
type = "apps"
match = ["firefox"]
tags = ["media"]

[channel.voip]
type = "apps"
match = ["discord", "fire"]
in_auto = false

[channel.alice]
type = "person"
person = ["Alice", "alice-phone"]

[channel.lights]
type = "homeassistant"

[pool.auto]
exclude = ["speech-dispatcher"]

[pool.media]
channels = ["#media"]
"""


def test_the_first_baseline_then_delays():
    delayed = Delayed(2, 30)
    assert not delayed.update(True, 0)
    assert delayed.value
    # off only after 30 s, and a return in between changes nothing
    assert not delayed.update(False, 1)
    assert delayed.deadline() == 31
    assert not delayed.update(True, 20)
    assert delayed.deadline() is None
    assert not delayed.update(False, 40)
    assert delayed.update(False, 70)
    assert not delayed.value
    # on after 2 s: a join tone of 1 s is nothing
    delayed.update(True, 80)
    delayed.update(False, 81)
    assert not delayed.value
    delayed.update(True, 90)
    assert delayed.update(True, 92)


def test_channels_are_present_while_they_have_something_to_control():
    read = scene(SCENE)
    nothing = Observation()
    there = Observation(
        playing=("Firefox",), devices=frozenset({"bluez_output.7C", "usb_mic"}), people=attendees("alice-phone")
    )
    assert {name for name, c in read.channels.items() if present_now(c, nothing)} == {"out", "lights"}
    assert {name for name, c in read.channels.items() if present_now(c, there)} == {
        "out",
        "buds",
        "mic",
        "browser",
        "voip",
        "alice",
        "lights",
    }


def test_presence_keeps_a_channel_for_absent_after():
    read = scene(SCENE)
    presence = Presence(read, absent_after=3)
    assert "browser" in presence.update(Observation(playing=("firefox",), devices=frozenset({"bluez_output.1"})), 0)
    present = presence.update(Observation(), 1)
    assert {"browser", "buds"} <= present
    assert presence.deadline() == 2  # buds has its own absent_after
    assert "buds" not in presence.update(Observation(), 2)
    assert "browser" not in presence.update(Observation(), 4)
    assert presence.deadline() is None


def test_which_channel_has_an_application_and_what_auto_never_takes():
    read = scene(SCENE)
    assert owner_of(read, "firefox") == "browser"
    assert owner_of(read, "discord") == "voip"
    assert owner_of(read, "spotify") is None
    assert excluded(read, "Speech-Dispatcher")
    assert excluded(read, "discord")
    assert not excluded(read, "firefox")
    assert not excluded(read, "spotify")


def test_pools_are_present_before_slots_are_assigned():
    read = scene(SCENE)
    assert not pool_present(read, "auto", Observation(playing=("discord", "speech-dispatcher")), frozenset())
    assert pool_present(read, "auto", Observation(playing=("discord", "firefox")), frozenset())
    # people share the slots of auto: anyone in the voice chat (before the slots are assigned)
    assert pool_present(read, "auto", Observation(people=attendees("Alice")), frozenset())
    # not someone whose person channel never goes into auto
    hidden = scene('[channel.alice]\ntype = "person"\nperson = "Alice"\nin_auto = false\n')
    assert not pool_present(hidden, "auto", Observation(people=attendees("Alice")), frozenset())
    assert not pool_present(read, "media", Observation(), frozenset({"out"}))
    assert pool_present(read, "media", Observation(), frozenset({"browser"}))
