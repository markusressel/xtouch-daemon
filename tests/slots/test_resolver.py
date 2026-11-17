"""
What the slots show: channels by rank, ties to the left, held slots, pools and their members, and why. The scenarios
of the reviews of the design are here by name.
"""

from tests.support.slots import attendees, older, scene, shows, states
from xtouch_daemon.slots.inputs import App, Channel, Observation, Person
from xtouch_daemon.slots.model import PEOPLE
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
    read = older()
    present = frozenset(read.channels)
    people = Observation(people=attendees("Bob"))
    gaming = resolve(read, Inputs(states(read, mode="gaming"), present, people))
    assert shows(gaming, [1, 2, 6]) == ["game", "-", "people:Bob"]
    after = resolve(read, Inputs(states(read), present, people), gaming)
    assert shows(after, [1, 2, 6]) == ["out", "browser", "people:Bob"]


def test_a_hidden_channel_takes_an_auto_slot_as_a_whole():
    """The third review: while slot 2 is dark, Browser plays in an auto slot, not as two owners of a stream."""
    read = older()
    observation = Observation(playing=("firefox", "discord", "mpv"), people=attendees("Bob"))
    result = resolve(read, Inputs(states(read, mode="gaming"), frozenset(read.channels), observation))
    assert shows(result) == ["game", "-", "auto:browser", "auto:mpv", "auto", "people:Bob", "voip", "auto"]
    assert result.slots[3] == Shown(0, channel="browser", pool="auto", member=Channel("browser"))
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
    assert during.waiting == {"auto": (App("e"), App("f"))}
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
    result = run("", observation=Observation(playing=("a", "b")), pins={2: App("c")})
    assert shows(result, [1, 2, 3]) == ["auto:a", "auto:c", "auto:b"]
    playing = run("", observation=Observation(playing=("a", "b")), pins={2: App("a")})
    assert shows(playing, [1, 2, 3]) == ["auto:b", "auto:a", "auto"]
    assert shows(run("", pins={5: App("c")}), [5]) == ["auto:c"]
    # a pin of a slot that doesn't show auto now waits; one of an application that plays isn't another member
    assert shows(run('[slots]\n1 = "out"', observation=Observation(playing=("a",)), pins={1: App("a")}), [1, 2]) == [
        "out",
        "auto:a",
    ]


def test_people_share_the_slots_of_auto():
    bob = Observation(people=attendees("Alice", "Bob"))
    result = run('[slots]\n1 = "alice"', observation=bob)
    assert shows(result, [1, 7, 8]) == ["alice", "auto", "people:Bob"]
    # a person channel without a slot joins them as itself
    result = run("", observation=bob)
    assert shows(result, [7, 8]) == ["people:Bob", "people:alice"]
    assert result.slots[8] == Shown(0, channel="alice", pool="people", member=Person("id-Alice", "Alice", "alice"))
    # unless it opts out
    read = scene(SCENE.replace('person = "Alice"', 'person = "Alice"\nin_auto = false'))
    assert shows(resolve(read, Inputs(states(read), ALL, bob)), [7, 8]) == ["auto", "people:Bob"]
    waiting = run("[slots]\n" + "".join(f'{slot} = "-"\n' for slot in range(1, 8)), observation=bob)
    assert shows(waiting, [8]) == ["people:alice"]
    assert waiting.waiting == {"people": (Person("id-Bob", "Bob"),)}
    # without a slot of auto, everybody waits
    nowhere = run(
        "[slots]\n" + "".join(f'{slot} = "-"\n' for slot in range(1, 9)), observation=Observation(playing=("mpv",))
    )
    assert nowhere.waiting == {"auto": (App("mpv"),)}


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
    text = '[slots]\n1 = ["auto if present", "out"]\n2 = ["media if present", "browser"]'
    assert shows(run(text, present=ALL - {"spotify", "radio"}), [1, 2]) == ["out", "browser"]
    # people share the slots of auto: auto is present with them
    assert shows(run(text, observation=Observation(people=attendees("Bob"))), [1, 2, 8]) == [
        "auto",
        "media:spotify",
        "people:Bob",
    ]


def test_shown_as_text():
    assert str(Shown(None)) == "-"
    assert str(Shown(0, channel="out")) == "out"
    assert str(Shown(0, pool="auto")) == "auto"
    assert str(Shown(0, pool="auto", member=App("mpv"))) == "auto:mpv"


# -- the code review -----------------------------------------------------------------------------------------------


def test_a_held_slot_keeps_a_channel_it_shows_as_a_member_of_auto():
    """Call ends while slot 3 dwells on Browser in auto: slot 2 doesn't show Browser too."""
    text = '[slots]\n1 = "out"\n2 = ["- if call", "browser"]\n3 = "auto"\n'
    firefox = Observation(playing=("firefox",))
    before = run(text, "call", observation=firefox)
    assert shows(before, [2, 3]) == ["-", "auto:browser"]
    after = run(text, previous=before, observation=firefox, fixed=frozenset({3}))
    assert shows(after, [2, 3]) == ["auto", "auto:browser"]
    assert "browser: browser is on a held slot" in after.why[2]


def test_a_pinned_channel_that_got_a_slot_of_its_own_is_shown_there_only():
    read = older()
    result = resolve(
        read,
        Inputs(states(read), frozenset(read.channels), Observation(playing=("firefox",)), pins={3: Channel("browser")}),
    )
    assert shows(result, [2, 3]) == ["browser", "auto"]
    assert result.why[3][0] == "pin browser: on another slot"


def test_a_pool_of_channels_gets_its_channel_before_auto_takes_it():
    result = run('[slots]\n1 = "media"\n2 = "auto"', observation=Observation(playing=("spotify",)))
    assert shows(result, [1, 2]) == ["media:spotify", "auto"]


def test_people_leave_pinned_slots_to_applications():
    result = run("", observation=Observation(people=attendees("Bob", "Carol")), pins={8: App("mpv")})
    assert shows(result, [6, 7, 8]) == ["people:Carol", "people:Bob", "auto:mpv"]
    # a pin of a channel that has a slot of its own keeps nobody out
    result = run(
        '[slots]\n1 = "browser"\n', observation=Observation(people=attendees("Bob")), pins={8: Channel("browser")}
    )
    assert shows(result, [1, 8]) == ["browser", "people:Bob"]


def test_a_pin_waits_while_a_held_slot_shows_its_member():
    """mpv, pinned to 5, moved to 3 while 5 had a channel; 3 is held: mpv doesn't show on 5 too."""
    text = '[slots]\n5 = ["out if call", "auto"]\n1 = "-"\n2 = "-"\n'
    mpv = Observation(playing=("mpv",))
    before = run(text, "call", observation=mpv, pins={5: App("mpv")})
    assert shows(before, [3, 5]) == ["auto:mpv", "out"]
    after = run(text, previous=before, observation=mpv, pins={5: App("mpv")}, fixed=frozenset({3}))
    assert shows(after, [3, 5]) == ["auto:mpv", "auto"]
    assert "pin mpv: on another slot" in after.why[5]


def test_people_and_applications_are_told_apart_from_channels():
    """Someone called browser in the voice chat is no channel, nor is an application called out."""
    result = run('[slots]\n1 = "-"\n', observation=Observation(playing=("out", "firefox"), people=attendees("browser")))
    assert result.slots[8] == Shown(0, pool="people", member=Person("id-browser", "browser"))
    assert result.slots[2] == Shown(0, pool="auto", member=App("out"))
    assert result.slots[3] == Shown(0, channel="browser", pool="auto", member=Channel("browser"))


def test_people_share_the_auto_slots_as_a_block_from_the_right_in_their_order():
    """Applications fill auto from the left, people from the right (next to VoIP) in their order."""
    slots = '[slots]\n1 = "out"\n2 = "browser"\n7 = ["voip if call", "auto"]\n8 = ["out if call", "auto"]\n'
    read = scene(SCENE + slots)

    def step(previous: Result | None, playing: tuple[str, ...], people: tuple[str, ...], order: tuple[str, ...] = ()):
        observation = Observation(playing=playing, people=attendees(*people))
        return resolve(read, Inputs(states(read), ALL, observation, order=order), previous)

    order = ("Bob", "Carol", "Dave")
    first = step(None, ("mpv",), ("Carol",), order)
    # slots 3-6 have auto first: Carol on 6, not on 8 (out while call is on)
    assert shows(first, [3, 4, 5, 6, 7, 8]) == ["auto:mpv", "auto", "auto", "people:Carol", "auto", "auto"]
    # Bob comes first in the order: Carol moves one to the left
    bob = step(first, ("mpv", "vlc"), ("Carol", "Bob"), order)
    assert shows(bob, [3, 4, 5, 6]) == ["auto:mpv", "auto:vlc", "people:Carol", "people:Bob"]
    # the block needs vlc's slot: it goes to a free one (7, auto while call is off)
    dave = step(bob, ("mpv", "vlc"), ("Carol", "Bob", "Dave"), order)
    assert shows(dave, [3, 4, 5, 6, 7]) == ["auto:mpv", "people:Dave", "people:Carol", "people:Bob", "auto:vlc"]
    assert "auto:vlc: gives way to Dave" in dave.why[4]
    # someone not in the order comes after those who are; more people than slots wait (then slots 7 and 8)
    crowd = step(None, (), ("Eve", "Dave", "A", "B", "C", "D"), order)
    assert shows(crowd, [3, 4, 5, 6, 7, 8]) == [
        "people:B",
        "people:A",
        "people:Eve",
        "people:Dave",
        "people:D",
        "people:C",
    ]
    many = step(None, (), tuple("ABCDEFG"))
    assert many.waiting == {PEOPLE: (Person("id-G", "G"),)}
