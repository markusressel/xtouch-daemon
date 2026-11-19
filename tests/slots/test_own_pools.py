"""
Pools of your own: of applications (`match`, `exclude`, `hold`) and of people (`people`). A pool takes its members
before `apps`, `people` and `auto`, and only while a slot names it.
"""

from tests.support.slots import attendees, scene, shows
from xtouch_daemon.slots.inputs import Observation, PoolMembers, pool_people, pool_present
from xtouch_daemon.slots.simulation import Simulation

POOLS = """
[pool.games]
kind = "apps"
match = ["steam_app", "lutris"]
exclude = ["lutris-wrapper"]
hold = 3

[pool.friends]
kind = "people"
people = ["Ann", "bob"]

[pool.unused]
kind = "people"
people = ["Carl"]

[slots]
1 = ["games", "-"]
2 = ["games", "-"]
3 = ["friends", "-"]
4 = ["people", "apps", "-"]
5 = ["people", "apps", "-"]
6 = "-"
7 = "-"
8 = "-"
"""


def test_a_pool_of_applications_takes_what_it_matches_before_apps():
    simulation = Simulation(scene(POOLS))
    playing = Observation(playing=("steam_app_42", "lutris-wrapper", "mpv"))
    assert shows(simulation.step(playing, 0), [1, 2, 4, 5]) == [
        "games:steam_app_42",
        "-",
        "apps:lutris-wrapper",
        "apps:mpv",
    ]


def test_a_pool_of_applications_holds_one_that_stopped_for_its_own_hold():
    simulation = Simulation(scene(POOLS))
    simulation.step(Observation(playing=("steam_app_42",)), 0)
    assert shows(simulation.step(Observation(), 1), [1]) == ["games:steam_app_42"]
    assert simulation.deadline() == 4
    assert shows(simulation.step(Observation(), 4), [1]) == ["-"]


def test_a_pool_of_people_takes_who_it_lists_before_people():
    simulation = Simulation(scene(POOLS))
    chat = Observation(people=attendees("Carl", "Bob", "Ann"), voice_chat=True)
    # in the order of its list, by name ignoring case; Carl's pool is named by no slot: he is one of `people` (from
    # the right)
    assert shows(simulation.step(chat, 0), [3, 4, 5]) == ["friends:Ann", "-", "people:Carl"]
    assert [person.name for person in pool_people(scene(POOLS), "friends", chat, set())] == ["Ann", "Bob"]


def test_a_pool_is_present_while_it_has_a_member():
    read = scene(POOLS)
    assert pool_present(read, "friends", Observation(people=attendees("BOB")), frozenset())
    assert not pool_present(read, "friends", Observation(people=attendees("Carl")), frozenset())
    # people the pool takes are no members of `people`
    assert not pool_present(read, "people", Observation(people=attendees("Ann")), frozenset())
    assert pool_present(read, "games", Observation(pool_playing={"games": ("steam_app_1",)}), frozenset())
    assert not pool_present(read, "games", Observation(pool_playing={"games": ("lutris-wrapper",)}), frozenset())


def test_a_reload_keeps_what_the_pools_hold():
    before = PoolMembers(scene(POOLS), absent_after=5)
    before.update(Observation(playing=("steam_app_42",)), 0)
    before.update(Observation(), 1)

    after = PoolMembers(scene(POOLS), absent_after=5)
    after.carry(before)

    assert after.update(Observation(), 2).pool_playing == {"games": ("steam_app_42",)}
    assert after.deadline() == 4
