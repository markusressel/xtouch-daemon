"""
The slots over time: presence, states, the dwell time and held slots, as the daemon will run them.
"""

from tests.support.slots import EXAMPLE, example, scene, shows
from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.simulation import Simulation
from xtouch_daemon.slots.states import Override

GAMING = Observation(processes=frozenset({"reaper"}))
JOINED = Observation(processes=frozenset({"reaper"}), people=("Bob",), voice_chat=True)


def test_joining_mumble_while_gaming_changes_each_slot_once():
    """The third review: slot 2 at once, slot 8 after the delay_on of call, each once."""
    simulation = Simulation(example())
    assert shows(simulation.step(GAMING, 0), [2, 8]) == ["browser", "auto"]
    assert shows(simulation.step(JOINED, 10), [2, 8]) == ["people:Bob", "auto"]
    assert simulation.deadline() == 11  # the dwell of slot 2 (call is due at 12)
    assert shows(simulation.step(JOINED, 11), [2, 8]) == ["people:Bob", "auto"]
    assert shows(simulation.step(JOINED, 12), [2, 8]) == ["people:Bob", "mic"]
    assert simulation.states is not None
    assert simulation.states.reasons["call"] == "in a voice chat"


def test_a_slot_dwells_and_a_held_one_waits_for_the_finger():
    simulation = Simulation(example(), dwell=1.0)
    simulation.step(Observation(), 0)
    simulation.step(GAMING, 5)
    # gaming ends right away: slot 1 still dwells on Game
    assert shows(simulation.step(Observation(), 5.5), [1]) == ["game"]
    assert shows(simulation.step(Observation(), 16), [1]) == ["out"]
    simulation.step(GAMING, 20)
    simulation.step(Observation(), 30)
    # the mode ends after its delay_off of 10 s, while a finger is on fader 1: it waits for the finger
    assert shows(simulation.step(Observation(), 40, held=frozenset({1})), [1]) == ["game"]
    assert shows(simulation.step(Observation(), 41), [1]) == ["out"]
    assert simulation.deadline() == 42


def test_overrides_and_picks_kept_from_before():
    simulation = Simulation(example(), overrides={"call": Override.ON}, mode_pick="gaming")
    assert shows(simulation.step(Observation(), 0), [1, 8]) == ["game", "mic"]
    assert Simulation(example()).deadline() is None


def test_a_reconnect_in_the_voice_chat_moves_nothing():
    """Bob is gone for half a second (Mumble reconnects): slot 2 stays on him, like a channel within absent_after."""
    simulation = Simulation(example())
    simulation.step(JOINED, 0)
    assert shows(simulation.step(GAMING, 20), [2]) == ["people:Bob"]
    assert shows(simulation.step(JOINED, 20.5), [2]) == ["people:Bob"]
    # gone for good: after absent_after
    simulation.step(GAMING, 30)
    assert simulation.deadline() == 33
    assert shows(simulation.step(GAMING, 33), [2]) == ["browser"]


def test_auto_holds_an_application_that_stopped():
    """A notification sound keeps its auto slot for the hold of the pool, and only gets one."""
    simulation = Simulation(example())
    simulation.step(Observation(), 0)
    assert shows(simulation.step(Observation(playing=("paplay",)), 10), [3]) == ["auto:paplay"]
    assert shows(simulation.step(Observation(), 10.3), [3]) == ["auto:paplay"]
    assert simulation.deadline() == 11  # the dwell; the hold of 5 s ends at 15.3
    assert shows(simulation.step(Observation(), 11), [3]) == ["auto:paplay"]
    assert shows(simulation.step(Observation(), 15.3), [3]) == ["auto"]


def test_a_person_who_comes_back_gets_their_slot_again():
    """MPhone leaves the channel and comes back: no gap between them and VoIP, also within the dwell of the slot."""
    read = scene(
        EXAMPLE.read_text()
        .replace('[pool.people]\ncolor = "yellow"', '[pool.people]\ncolor = "yellow"\nshare = "auto"')
        .replace('2 = ["people if gaming and present", "browser"]', '2 = "browser"')
    )
    for back in (3.6, 4.3, 30.0):
        simulation = Simulation(read)
        talking = Observation(voice_chat=True, people=("MPhone",))
        assert shows(simulation.step(talking, 0), [6]) == ["people:MPhone"]
        t = 5.0
        while t < 5 + back:
            simulation.step(Observation(voice_chat=True), t)
            t = round(t + 0.2, 1)
        result = simulation.step(talking, t)
        while t < 5 + back + 2:
            t = round(t + 0.2, 1)
            result = simulation.step(talking, t)
        assert shows(result, [3, 4, 5, 6]) == ["auto", "auto", "auto", "people:MPhone"], back


def test_a_home_lasts_a_while():
    read = scene(EXAMPLE.read_text().replace('[pool.people]\ncolor = "yellow"', '[pool.people]\nshare = "auto"'))
    simulation = Simulation(read)
    simulation.step(Observation(voice_chat=True, people=("A",)), 0)
    simulation.step(Observation(voice_chat=True, people=("A", "B")), 1)
    simulation.step(Observation(voice_chat=True, people=("B",)), 10)
    # A's slot 6 is free; B stays on 5. A comes back much later: their home is gone, the rightmost free slot
    assert shows(simulation.step(Observation(voice_chat=True, people=("B",)), 20), [5, 6]) == ["people:B", "auto"]
    later = simulation.step(Observation(voice_chat=True, people=("B", "C", "A")), 2000)
    assert shows(later, [4, 5, 6]) == ["people:A", "people:B", "people:C"]
