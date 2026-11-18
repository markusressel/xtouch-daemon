"""
The slots over time: presence, states, the dwell time and held slots, as the daemon will run them.
"""

from dataclasses import replace

from tests.support.slots import OLDER, attendees, older, scene, shows
from xtouch_daemon.slots.inputs import Attendee, Observation, Person
from xtouch_daemon.slots.model import PEOPLE
from xtouch_daemon.slots.simulation import Simulation
from xtouch_daemon.slots.states import Override

GAMING = Observation(processes=frozenset({"reaper"}))
JOINED = Observation(processes=frozenset({"reaper"}), people=attendees("Bob"), voice_chat=True)


def test_joining_mumble_while_gaming_changes_each_slot_once():
    """The third review: Bob on an auto slot at once, the Mic after the delay_on of call, each once."""
    simulation = Simulation(older())
    assert shows(simulation.step(GAMING, 0), [6, 8]) == ["auto", "auto"]
    assert shows(simulation.step(JOINED, 10), [6, 8]) == ["people:Bob", "auto"]
    assert simulation.deadline() == 11  # the dwell of slot 6 (call is due at 12)
    assert shows(simulation.step(JOINED, 11), [6, 8]) == ["people:Bob", "auto"]
    assert shows(simulation.step(JOINED, 12), [6, 8]) == ["people:Bob", "mic"]
    assert simulation.states is not None
    assert simulation.states.reasons["call"] == "in a voice chat"


def test_a_slot_dwells_and_a_held_one_waits_for_the_finger():
    simulation = Simulation(older(), dwell=1.0)
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
    simulation = Simulation(older(), overrides={"call": Override.ON}, mode_pick="gaming")
    assert shows(simulation.step(Observation(), 0), [1, 8]) == ["game", "mic"]
    assert Simulation(older()).deadline() is None


def test_a_reconnect_in_the_voice_chat_moves_nothing():
    """Bob is gone for half a second (Mumble reconnects): slot 6 stays on him, like a channel within absent_after."""
    simulation = Simulation(older())
    simulation.step(JOINED, 0)
    assert shows(simulation.step(GAMING, 20), [6]) == ["people:Bob"]
    assert shows(simulation.step(JOINED, 20.5), [6]) == ["people:Bob"]
    # the voice chat gives him a new id when he comes back: he is still the one on slot 6, once
    again = replace(JOINED, people=(Attendee("new-Bob", "Bob"),))
    simulation.step(GAMING, 25)
    result = simulation.step(again, 25.5)
    assert result.slots[6].member == Person("new-Bob", "Bob")
    assert PEOPLE not in result.waiting
    # gone for good: after absent_after
    simulation.step(GAMING, 30)
    assert simulation.deadline() == 33
    assert shows(simulation.step(GAMING, 33), [6]) == ["auto"]


def test_auto_holds_an_application_that_stopped():
    """A notification sound keeps its auto slot for the hold of the pool, and only gets one."""
    simulation = Simulation(older())
    simulation.step(Observation(), 0)
    assert shows(simulation.step(Observation(playing=("paplay",)), 10), [3]) == ["auto:paplay"]
    assert shows(simulation.step(Observation(), 10.3), [3]) == ["auto:paplay"]
    assert simulation.deadline() == 11  # the dwell; the hold of 5 s ends at 15.3
    assert shows(simulation.step(Observation(), 11), [3]) == ["auto:paplay"]
    assert shows(simulation.step(Observation(), 15.3), [3]) == ["auto"]


def test_the_order_of_people_is_configured_then_learned():
    read = scene(OLDER.read_text().replace("[pool.people]\n", '[pool.people]\norder = ["Bob"]\n'))
    simulation = Simulation(read, known={"Old": -1e9, "Carol": 0.0})
    talking = Observation(voice_chat=True)
    simulation.step(replace(talking, people=attendees("Dave")), 1)
    # Old was not seen for too long; Bob is configured, the others in the order they were seen first
    assert simulation.order == ("Bob", "Carol", "Dave")
    assert list(simulation.known) == ["Carol", "Dave"]
    result = simulation.step(replace(talking, people=attendees("Dave", "Bob", "Carol")), 2)
    assert shows(result, [4, 5, 6]) == ["people:Dave", "people:Carol", "people:Bob"]
