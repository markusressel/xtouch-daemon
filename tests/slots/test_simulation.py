"""
The slots over time: presence, states, the dwell time and held slots, as the daemon will run them.
"""

from tests.support.slots import example, shows
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
