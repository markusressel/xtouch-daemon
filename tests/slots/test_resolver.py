"""
What the slots show: channels by rank, ties to the left, held slots, pools and their members, and why. The scenarios
of the reviews of the design are here by name.
"""

from tests.support.slots import example, scene, shows, states
from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.model import AUTO, PEOPLE
from xtouch_daemon.slots.resolver import Inputs, Result, Shown, resolve

SCENE = """
[channel.out]
type = "output"

[channel.browser]
type = "apps"
match = ["firefox"]
label = "Browser"

[channel.spotify]
type = "apps"
match = ["spotify"]
tags = ["media"]

[channel.radio]
type = "apps"
match = ["radio"]
tags = ["media"]

[channel.voip]
type = "apps"
match = ["discord"]
in_auto = false

[channel.alice]
type = "person"
person = "Alice"

[channel.buds]
type = "output"
device = "bluez_output.*"

[pool.media]
channels = ["#media"]

[state.call]
voice_chat = true

[state.gaming]
mode = true
processes = ["reaper"]
"""

ALL = frozenset({"out", "browser", "spotify", "radio", "voip", "alice", "buds"})


def run(
    text: str,
    *on: str,
    mode: str = "default",
    present: frozenset[str] = ALL,
    previous: Result | None = None,
    **inputs: object,
) -> Result:
    read = scene(SCENE + text)
    return resolve(read, Inputs(states(read, *on, mode=mode), present, **inputs), previous)  # pyright: ignore[reportArgumentType]


# -- the example ---------------------------------------------------------------------------------------------------


def test_browser_goes_back_to_slot_2_when_gaming_ends():
    """The second review: with stickiness, slot 2 stayed dark after gaming. Now the result has no history."""
    read = example()
    present = frozenset(read.channels)
    people = Observation(people=("Bob",))
    gaming = resolve(read, Inputs(states(read, mode="gaming"), present, people))
    assert shows(gaming, [1, 2, 8]) == ["game", "people:Bob", "auto"]
    after = resolve(read, Inputs(states(read), present, people), gaming)
    assert shows(after, [1, 2, 8]) == ["out", "browser", "auto"]


def test_a_hidden_channel_takes_an_auto_slot_as_a_whole():
    """The third review: while slot 2 shows people, Browser plays in an auto slot, not as two owners of a stream."""
    read = example()
    observation = Observation(playing=("firefox", "discord", "mpv"), people=("Bob",))
    result = resolve(read, Inputs(states(read, mode="gaming"), frozenset(read.channels), observation))
    assert shows(result) == ["game", "people:Bob", "auto:browser", "auto:mpv", "auto", "auto", "voip", "auto"]
    assert result.slots[3] == Shown(0, channel="browser", pool="auto", member="browser")
    assert result.slot_of("browser") == 3
    assert result.slot_of("mic") is None


# -- channels ------------------------------------------------------------------------------------------------------


def test_a_channel_goes_to_its_highest_rank_then_to_the_left():
    result = run('[slots]\n1 = ["spotify if call", "browser"]\n2 = ["browser"]\n3 = ["browser"]', "call")
    assert shows(result, [1, 2, 3]) == ["spotify", "browser", "auto"]
    assert result.why[3] == ("browser: on slot 2 (tie, to the left)", "shows auto")
    result = run('[slots]\n1 = ["spotify if call", "browser"]\n2 = ["browser"]')
    assert shows(result, [1, 2]) == ["auto", "browser"]
    assert result.why[1] == (
        "spotify if call: doesn't hold (call is off)",
        "browser: on slot 2 (rank 1 there, 2 here)",
        "shows auto",
    )


def test_an_absent_channel_keeps_its_place_unless_it_asks_for_presence():
    absent = ALL - {"buds"}
    assert shows(run('[slots]\n1 = "buds"', present=absent), [1]) == ["buds"]
    result = run('[slots]\n1 = ["buds if present", "out"]', present=absent)
    assert shows(result, [1]) == ["out"]
    assert result.why[1][0] == "buds if present: doesn't hold (present: no)"


def test_nothing_on_purpose():
    result = run('[slots]\n1 = "-"\n2 = ["- if call", "out"]\n3 = ["- if call", "browser"]', "call")
    assert shows(result, [1, 2, 3]) == ["-", "-", "-"]
    assert result.slots[1] == Shown(0)


# -- held slots ----------------------------------------------------------------------------------------------------


def test_a_held_slot_keeps_its_channel_and_the_others_resolve_around_it():
    """The third review: a held slot 8 on Browser while slot 2 now ranks Browser higher."""
    text = '[slots]\n2 = ["spotify if call", "browser"]\n8 = ["browser if call", "auto"]'
    before = run(text, "call")
    assert shows(before, [2, 8]) == ["spotify", "browser"]
    after = run(text, previous=before, fixed=frozenset({8}))
    assert shows(after, [2, 8]) == ["auto", "browser"]
    assert after.why[2][-2:] == ("browser: browser is on a held slot", "shows auto")
    assert after.why[8] == ("held", "shows browser")
    # a held slot is nothing without a result before (the start)
    assert shows(run(text, fixed=frozenset({8})), [2, 8]) == ["browser", "auto"]


def test_a_held_pool_slot_keeps_its_member():
    first = run("", observation=Observation(playing=("a", "b")))
    assert shows(first, [1, 2]) == ["auto:a", "auto:b"]
    held = run(
        '[slots]\n1 = ["out"]', previous=first, fixed=frozenset({2}), observation=Observation(playing=("a", "b"))
    )
    assert shows(held, [1, 2, 3]) == ["out", "auto:b", "auto:a"]


# -- pools ---------------------------------------------------------------------------------------------------------


def test_applications_keep_their_slots_and_wait_when_a_call_takes_one():
    """The third review: 6 applications on slots 3 to 8, then a call takes 7 and 8."""
    text = '[slots]\n1 = "out"\n2 = "browser"\n7 = ["voip if call", "auto"]\n8 = ["alice if call", "auto"]'
    playing = Observation(playing=("a", "b", "c", "d", "e", "f"))
    before = run(text, observation=playing)
    assert shows(before, range(3, 9)) == ["auto:a", "auto:b", "auto:c", "auto:d", "auto:e", "auto:f"]
    during = run(text, "call", observation=playing, previous=before)
    assert shows(during, range(3, 9)) == ["auto:a", "auto:b", "auto:c", "auto:d", "voip", "alice"]
    assert during.waiting == {"auto": ("e", "f")}
    # the others don't move when one stops: the slot of b takes the next one
    later = run(text, "call", observation=Observation(playing=("a", "c", "d", "e", "f")), previous=during)
    assert shows(later, range(3, 7)) == ["auto:a", "auto:e", "auto:c", "auto:d"]
    after = run(text, observation=Observation(playing=("a", "c", "d", "e", "f")), previous=later)
    assert shows(after, range(3, 9)) == ["auto:a", "auto:e", "auto:c", "auto:d", "auto:f", "auto"]


def test_what_auto_takes():
    playing = Observation(playing=("firefox", "discord", "spotify-client", "mpv"))
    result = run('[slots]\n1 = "spotify"', observation=playing)
    # the browser as a whole, not discord (in_auto = false), not spotify (it has a slot)
    assert shows(result, [1, 2, 3, 4]) == ["spotify", "auto:browser", "auto:mpv", "auto"]


def test_a_pin_beats_the_order_and_stays_after_its_application_stopped():
    result = run("", observation=Observation(playing=("a", "b")), pins={2: "c"})
    assert shows(result, [1, 2, 3]) == ["auto:a", "auto:c", "auto:b"]
    playing = run("", observation=Observation(playing=("a", "b")), pins={2: "a"})
    assert shows(playing, [1, 2, 3]) == ["auto:b", "auto:a", "auto"]
    assert shows(run("", pins={5: "c"}), [5]) == ["auto:c"]
    # a pin of a slot that doesn't show auto now waits; one of an application that plays isn't another member
    assert shows(run('[slots]\n1 = "out"', observation=Observation(playing=("a",)), pins={1: "a"}), [1, 2]) == [
        "out",
        "auto:a",
    ]


def test_people_without_a_channel_of_their_own():
    result = run('[slots]\n1 = "alice"\n2 = "people"\n3 = "people"', observation=Observation(people=("Alice", "Bob")))
    assert shows(result, [1, 2, 3]) == ["alice", "people:Bob", "people"]
    waiting = run('[slots]\n2 = "people"', observation=Observation(people=("Bob", "Carol")))
    assert waiting.waiting == {"people": ("Carol",)}
    # without a slot of the pool, everybody waits
    assert run("", observation=Observation(people=("Bob",))).waiting == {"people": ("Bob",)}


def test_a_pool_of_channels_fills_by_its_order():
    text = '[slots]\n1 = "media"\n2 = "media"\n3 = ["radio if call", "auto"]'
    result = run(text)
    assert shows(result, [1, 2]) == ["media:spotify", "media:radio"]
    assert result.slots[1].channel == "spotify"
    # radio has a slot of its own now: not a member any more
    assert shows(run(text, "call", previous=result), [1, 2, 3]) == ["media:spotify", "media", "radio"]
    # spotify comes back: it takes its place, radio moves on (collapse without moving the other strips)
    absent = run(text, present=ALL - {"spotify"})
    assert shows(absent, [1, 2]) == ["media:radio", "media"]
    assert shows(run(text, previous=absent), [1, 2]) == ["media:spotify", "media:radio"]


def test_pools_by_presence():
    text = '[slots]\n1 = ["people if present", "out"]\n2 = ["auto if present(people)", "browser"]'
    assert shows(run(text), [1, 2]) == ["out", "browser"]
    assert shows(run(text, observation=Observation(people=("Bob",))), [1, 2]) == ["people:Bob", "auto"]


def test_shown_as_text():
    assert str(Shown(None)) == "-"
    assert str(Shown(0, channel="out")) == "out"
    assert str(Shown(0, pool="auto")) == "auto"
    assert str(Shown(0, pool="auto", member="mpv")) == "auto:mpv"


# -- the code review -----------------------------------------------------------------------------------------------


def test_a_held_slot_keeps_a_channel_it_shows_as_a_member_of_auto():
    """Bob leaves while slot 3 dwells on Browser in auto: slot 2 doesn't show Browser too."""
    read = example()
    present = frozenset(read.channels)
    before = resolve(
        read,
        Inputs(states(read, mode="gaming"), present, Observation(playing=("firefox",), people=("Bob",))),
    )
    assert shows(before, [2, 3]) == ["people:Bob", "auto:browser"]
    after = resolve(
        read,
        Inputs(states(read, mode="gaming"), present, Observation(playing=("firefox",)), fixed=frozenset({3})),
        before,
    )
    # people is empty, browser is on slot 3: on to auto, which has nothing else
    assert shows(after, [2, 3]) == ["auto", "auto:browser"]
    assert "browser: browser is on a held slot" in after.why[2]


def test_a_pinned_channel_that_got_a_slot_of_its_own_is_shown_there_only():
    read = example()
    result = resolve(
        read, Inputs(states(read), frozenset(read.channels), Observation(playing=("firefox",)), pins={3: "browser"})
    )
    assert shows(result, [2, 3]) == ["browser", "auto"]
    assert result.why[3][0] == "pin browser: on another slot"


def test_a_pool_of_channels_gets_its_channel_before_auto_takes_it():
    result = run('[slots]\n1 = "media"\n2 = "auto"', observation=Observation(playing=("spotify",)))
    assert shows(result, [1, 2]) == ["media:spotify", "auto"]


def test_people_share_the_auto_slots_from_the_right_and_nobody_moves():
    """Applications fill auto from the left, people from the right (next to VoIP): coming and going moves no one."""
    read = scene(SCENE + '[pool.people]\nshare = "auto"\n[slots]\n1 = "out"\n2 = "browser"\n7 = "voip"\n8 = "-"\n')
    present = ALL

    def step(previous: Result | None, playing: tuple[str, ...], people: tuple[str, ...]) -> Result:
        return resolve(read, Inputs(states(read), present, Observation(playing=playing, people=people)), previous)

    first = step(None, ("mpv",), ())
    assert shows(first, [3, 4, 5, 6]) == ["auto:mpv", "auto", "auto", "auto"]
    bob = step(first, ("mpv",), ("Bob",))
    assert shows(bob, [3, 4, 5, 6]) == ["auto:mpv", "auto", "auto", "people:Bob"]
    carol = step(bob, ("mpv", "vlc"), ("Bob", "Carol"))
    assert shows(carol, [3, 4, 5, 6]) == ["auto:mpv", "auto:vlc", "people:Carol", "people:Bob"]
    # full: Dave takes the rightmost slot left, vlc gives way and waits
    dave = step(carol, ("mpv", "vlc"), ("Bob", "Carol", "Dave"))
    assert shows(dave, [3, 4, 5, 6]) == ["auto:mpv", "people:Dave", "people:Carol", "people:Bob"]
    assert dave.waiting == {AUTO: ("vlc",)}
    assert "auto: gives way to Dave" in dave.why[4]
    # Bob leaves: vlc gets his slot, nobody else moves
    gone = step(dave, ("mpv", "vlc"), ("Carol", "Dave"))
    assert shows(gone, [3, 4, 5, 6]) == ["auto:mpv", "people:Dave", "people:Carol", "auto:vlc"]
    # five people for four slots: one waits
    crowd = step(None, (), ("A", "B", "C", "D", "E"))
    assert shows(crowd, [3, 4, 5, 6]) == ["people:D", "people:C", "people:B", "people:A"]
    assert crowd.waiting == {PEOPLE: ("E",)}


def test_people_of_their_own_slots_first_then_auto_slots():
    read = scene(
        SCENE
        + '[pool.people]\nshare = "auto"\n[slots]\n1 = "people"\n2 = "-"\n3 = "-"\n4 = "-"\n5 = "-"\n6 = "-"\n7 = "-"\n'
    )
    result = resolve(read, Inputs(states(read), ALL, Observation(people=("Bob", "Carol"))))
    assert shows(result, [1, 8]) == ["people:Bob", "people:Carol"]


def test_people_take_the_auto_slots_nothing_takes_over_first():
    """At a start the voice chat is there before call (its delay_on): the person must not take slot 8, mic's."""
    slots = '[slots]\n1 = "out"\n2 = "browser"\n7 = ["voip if call", "auto"]\n8 = ["out if call", "auto"]\n'
    read = scene(SCENE + '[pool.people]\nshare = "auto"\n' + slots)
    playing = ("a", "b", "c", "d")
    before = resolve(read, Inputs(states(read), ALL, Observation(people=("Bob",))))
    assert shows(before, [6, 7, 8]) == ["people:Bob", "auto", "auto"]
    # 3-6 full of applications that keep their slots: the free slot 8 first, then the rightmost stable one
    full = resolve(read, Inputs(states(read), ALL, Observation(playing=playing)))
    joined = resolve(read, Inputs(states(read), ALL, Observation(playing=playing, people=("Bob", "Carol"))), full)
    assert shows(joined, [6, 7, 8]) == ["auto:d", "people:Carol", "people:Bob"]
