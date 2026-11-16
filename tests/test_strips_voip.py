import asyncio
import dataclasses
from collections.abc import AsyncIterator

import pytest

from tests.conftest import FakeLauncher, RecordingSurface, finish_tasks, settle
from xtouch_daemon.audio.model import DISCONNECTED
from xtouch_daemon.config.layout_strips import VoipStripConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.strips import voip as voip_module
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.voip import VoipSeat, VoipSeats, VoipStrip
from xtouch_daemon.system.launch import LaunchButton
from xtouch_daemon.voip import Capability, Participant, VoipProvider

CONFIG = VoipStripConfig(type="voip", color="cyan", talking_color="green", max_volume=200)


class FakeProvider(VoipProvider):
    """Records the commands; the participants are set by the tests."""

    def __init__(self, capabilities: frozenset[Capability] = frozenset(Capability)):
        super().__init__(capabilities)
        self.commands: list[tuple[str, str, object]] = []

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def set_volume(self, participant_id: str, volume: int) -> None:
        self.commands.append(("volume", participant_id, volume))

    async def set_muted(self, participant_id: str, muted: bool) -> None:
        self.commands.append(("muted", participant_id, muted))


PEOPLE = (
    Participant("1", "Annabelle", talking=True, volume=100, level=0.5),
    Participant("2", "Bob", muted=True, volume=50),
    Participant("3", "Carol", volume=150),
)


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


@pytest.fixture
def provider() -> FakeProvider:
    provider = FakeProvider()
    provider.update(PEOPLE)
    return provider


def make(
    surface: RecordingSurface,
    env: StripEnv,
    provider: VoipProvider,
    *configs: VoipStripConfig,
    launch: LaunchButton | None = None,
) -> tuple[VoipSeats, list[VoipStrip], list[int]]:
    """`voip` strips of these configurations (by default two of the group) on the first strips of the surface."""
    configs = configs or (CONFIG, CONFIG)
    refreshed: list[int] = []
    strips: list[VoipStrip] = []

    def refresh() -> None:
        refreshed.append(1)
        for strip in strips:
            strip.show()

    seats = VoipSeats(provider, [config.person for config in configs], refresh)
    strips += [
        VoipStrip(surface.strips[seat], env, VoipSeat(seats, seat, launch), config)
        for seat, config in enumerate(configs)
    ]
    return seats, strips, refreshed


def fixed(*names: str, **options: object) -> VoipStripConfig:
    return CONFIG.model_copy(update={"person": names, **options})


def test_the_pages_of_a_group(provider: FakeProvider):
    seats = VoipSeats(provider, [(), ()])
    assert seats.pages == 2
    assert [seats.participant(seat) for seat in (0, 1)] == list(PEOPLE[:2])
    assert seats.next_page() == "pg 2/2"
    assert [seats.participant(seat) for seat in (0, 1)] == [PEOPLE[2], None]
    assert seats.next_page() == "pg 1/2"
    seats.page = 1
    provider.update(PEOPLE[:1])
    # fewer participants: the page wraps
    assert seats.pages == 1
    assert seats.participant(0) == PEOPLE[0]
    assert VoipSeats(FakeProvider(), [(), (), ()]).pages == 1


def test_the_group_is_the_strips_without_a_person(provider: FakeProvider):
    # not next to each other: the group fills its strips in order with the people without a strip of their own
    seats = VoipSeats(provider, [(), ("bob",), ()])
    assert seats.group == (0, 2)
    assert [seats.participant(seat) for seat in range(3)] == [PEOPLE[0], PEOPLE[1], PEOPLE[2]]
    assert seats.pages == 1
    assert seats.fixed(1)
    assert not seats.fixed(0)
    # only fixed strips: one page, nothing to page
    assert VoipSeats(provider, [("carol",)]).pages == 1


def test_a_person_has_names_ignoring_case(provider: FakeProvider):
    seats = VoipSeats(provider, [("Carol", "carol-phone"), ()])
    assert seats.participant(0) == PEOPLE[2]
    assert seats.participant(1) == PEOPLE[0]
    phone = Participant("4", "CAROL-PHONE")
    provider.update((phone, *PEOPLE))
    # the first one of the names in the order of the provider; the other one goes to the group
    assert seats.participant(0) == phone
    assert [seats.participant(1), seats.pages] == [PEOPLE[0], 3]
    # no wildcards, no parts of a name
    assert VoipSeats(provider, [("caro",)]).participant(0) is None


def test_the_seats_follow_the_provider(provider: FakeProvider):
    seats = VoipSeats(provider, [("bob",), ()])
    assert seats.participant(1) == PEOPLE[0]
    provider.update(PEOPLE[1:])
    assert seats.participant(1) == PEOPLE[2]
    provider.update(PEOPLE[2:])
    assert seats.participant(0) is None


async def test_a_strip_shows_its_participant(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    _, (ann, bob), _ = make(surface, env, provider)
    ann.update(DISCONNECTED)
    bob.update(DISCONNECTED)
    await settle()
    first, second = surface.strips[:2]
    assert (first.color, first.text, first.leds[Button.MUTE]) == (Color.GREEN, ["Annabel", "100%"], Led.OFF)
    # 100 % at the 0 dB mark (`behavior.unity_at`), as on the other strips
    assert first.fader == protocol.fader_value(0.77)
    # more participants than places: Select pages
    assert first.leds[Button.SELECT] == Led.ON
    assert (second.color, second.text, second.leds[Button.MUTE]) == (Color.CYAN, ["Bob", "muted"], Led.ON)
    assert ann.held_meter() == round(0.5 * protocol.METER_MAX)
    assert bob.held_meter() is None


async def test_without_volumes_and_levels(surface: RecordingSurface, env: StripEnv):
    provider = FakeProvider(frozenset())
    provider.update((Participant("1", "Ann", talking=True), Participant("2", "Bob")))
    _, (ann, bob), _ = make(surface, env, provider)
    ann.update(DISCONNECTED)
    bob.update(DISCONNECTED)
    assert surface.strips[0].text == ["Ann", "talks"]
    assert surface.strips[1].text == ["Bob", ""]
    assert surface.strips[0].fader == 0
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF
    # a talking participant fills the meter, a silent one leaves it
    assert ann.held_meter() == protocol.METER_MAX - 1
    assert bob.held_meter() is None
    ann.on_fader(0.5)
    ann.on_button(Button.MUTE, True)
    await settle()
    assert provider.commands == []


async def test_an_empty_place_is_dark(surface: RecordingSurface, env: StripEnv):
    provider = FakeProvider()
    _, (empty, _), _ = make(surface, env, provider)
    empty.update(DISCONNECTED)
    strip = surface.strips[0]
    assert (strip.color, strip.text, strip.fader) == (Color.BLACK, ["", ""], 0)
    assert empty.held_meter() is None
    empty.on_fader(0.7)
    empty.on_button(Button.MUTE, True)
    await settle()
    assert provider.commands == []


async def test_the_meter_can_be_off(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    _, (ann, _), _ = make(surface, env, provider, CONFIG.model_copy(update={"meter": False}), CONFIG)
    assert ann.held_meter() is None


async def test_the_fader_sets_the_volume(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    _, (ann, _), _ = make(surface, env, provider)
    ann.update(DISCONNECTED)
    surface.strips[0].touch(True)
    ann.on_touch(True)
    ann.on_fader(0.25)
    # the same volume again sends nothing
    ann.on_fader(0.25)
    await settle()
    # a quarter of the way to the 0 dB mark at 77 %
    assert provider.commands == [("volume", "1", 32)]
    assert surface.strips[0].text[1] == "32%"
    # until the provider tells it, the strip shows what the fader set
    ann.update(DISCONNECTED)
    assert surface.strips[0].text[1] == "32%"
    ann.on_touch(False)
    provider.update((Participant("1", "Annabelle", volume=32), *PEOPLE[1:]))
    ann.update(DISCONNECTED)
    assert surface.strips[0].text[1] == "32%"
    assert ann._wanted is None  # pyright: ignore[reportPrivateUsage]
    ann.on_fader(0.25)
    await settle()
    assert provider.commands == [("volume", "1", 32)]


async def test_mute_toggles_the_participant(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    _, (ann, bob), _ = make(surface, env, provider)
    ann.on_button(Button.MUTE, True)
    ann.on_button(Button.MUTE, False)
    bob.on_button(Button.MUTE, True)
    ann.on_button(Button.REC, True)
    await settle()
    assert provider.commands == [("muted", "1", True), ("muted", "2", False)]


async def test_select_shows_the_next_page(
    surface: RecordingSurface, env: StripEnv, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(voip_module, "NOTICE_TIME", 0.01)
    seats, (ann, bob), refreshed = make(surface, env, provider)
    bob.on_button(Button.SELECT, True)
    bob.on_button(Button.SELECT, False)
    assert seats.page == 1
    assert refreshed == [1]
    ann.update(DISCONNECTED)
    assert surface.strips[0].text == ["Carol", "150%"]
    assert surface.strips[1].text == ["", "pg 2/2"]
    # a second press while the page shows
    bob.on_button(Button.SELECT, True)
    assert surface.strips[1].text[1] == "pg 1/2"
    await asyncio.sleep(0.05)
    assert surface.strips[1].text == ["Bob", "muted"]
    bob.on_button(Button.SELECT, True)
    bob.close()
    ann.close()


# -- launch -------------------------------------------------------------------------------------------------------

MUMBLE = ("mumble", "mumble://markus@voice.example.org/Gaming")


def launching(
    surface: RecordingSurface, env: StripEnv, provider: VoipProvider, *processes: str
) -> tuple[FakeLauncher, list[VoipStrip]]:
    launcher = FakeLauncher()
    config = CONFIG.model_copy(update={"launch": MUMBLE})
    button = LaunchButton(MUMBLE, launcher, "Strip 1")
    env = dataclasses.replace(env, processes=lambda: frozenset(processes))
    _, strips, _ = make(surface, env, provider, config, config, launch=button)
    return launcher, strips


async def test_select_launches_the_voice_chat_while_it_is_not_there(surface: RecordingSurface, env: StripEnv):
    launcher, (first, second) = launching(surface, env, FakeProvider())
    assert first.launches
    first.update(DISCONNECTED)
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF

    first.on_button(Button.SELECT, True)
    # the places launch together: once
    second.on_button(Button.SELECT, True)

    assert len(launcher.spawned) == 1
    assert launcher.spawned[0][-2:] == list(MUMBLE)
    assert surface.strips[0].leds[Button.SELECT] == Led.FLASH
    assert surface.strips[1].leds[Button.SELECT] == Led.FLASH
    # no page notice
    assert surface.strips[0].text[1] == ""


async def test_a_voice_chat_that_is_there_pages_on_select(
    surface: RecordingSurface, env: StripEnv, provider: FakeProvider
):
    # the plugin reports it
    launcher, (first, _) = launching(surface, env, provider)
    first.on_button(Button.SELECT, True)
    assert launcher.spawned == []
    assert first.notice == "pg 2/2"
    assert surface.strips[0].leds[Button.SELECT] == Led.ON


async def test_the_program_of_launch_counts_as_the_voice_chat(surface: RecordingSurface, env: StripEnv):
    # Mumble runs without the plugin
    launcher, (first, _) = launching(surface, env, FakeProvider(), "mumble")
    first.on_button(Button.SELECT, True)
    assert launcher.spawned == []
    assert first.notice == "pg 1/1"


async def test_a_launch_that_fails_shows_nothing(surface: RecordingSurface, env: StripEnv):
    launcher, (first, _) = launching(surface, env, FakeProvider())
    launcher.missing.add("mumble")
    first.on_button(Button.SELECT, True)
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF
    assert first.notice is None


async def test_a_place_without_a_participant_is_absent(
    surface: RecordingSurface, env: StripEnv, provider: FakeProvider
):
    seats, strips, _ = make(surface, env, provider)
    seats.next_page()
    assert [strip.absent(DISCONNECTED) for strip in strips] == [False, True]
    assert [strip.title for strip in strips] == ["Carol", "voip"]


async def test_the_strips_of_a_person_launch_too(surface: RecordingSurface, env: StripEnv):
    launcher = FakeLauncher()
    button = LaunchButton(MUMBLE, launcher, "Strip 1")
    config = CONFIG.model_copy(update={"launch": MUMBLE, "person": ("carol",)})
    _, (carol,), _ = make(surface, env, FakeProvider(), config, launch=button)
    carol.on_button(Button.SELECT, True)
    assert len(launcher.spawned) == 1
    assert surface.strips[0].leds[Button.SELECT] == Led.FLASH


# -- strips of one person -----------------------------------------------------------------------------------------


async def test_a_strip_of_a_person(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    _, (carol, group), _ = make(surface, env, provider, fixed("carol", label="Mum"), CONFIG)
    carol.update(DISCONNECTED)
    group.update(DISCONNECTED)
    assert surface.strips[0].text == ["Mum", "150%"]
    assert (carol.title, carol.absent(DISCONNECTED)) == ("Mum", False)
    # the group has the two others, on one strip: two pages
    assert surface.strips[1].text == ["Annabel", "100%"]
    assert surface.strips[1].leds[Button.SELECT] == Led.ON
    # Select on the strip of a person pages nothing
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF
    carol.on_button(Button.SELECT, True)
    assert carol.notice is None
    carol.on_fader(0.25)
    carol.on_button(Button.MUTE, True)
    await settle()
    assert provider.commands == [("volume", "3", 32), ("muted", "3", True)]


async def test_a_person_who_is_away(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    _, (dave, _), _ = make(surface, env, provider, fixed("Dave"), CONFIG)
    dave.update(DISCONNECTED)
    strip = surface.strips[0]
    # the name stays, dark, with the fader down
    assert (strip.color, strip.text, strip.fader) == (Color.BLACK, ["Dave", "away"], 0)
    assert strip.leds[Button.MUTE] == Led.OFF
    assert dave.absent(DISCONNECTED)
    assert dave.title == "Dave"
    assert dave.held_meter() is None
    dave.on_fader(0.5)
    dave.on_button(Button.MUTE, True)
    await settle()
    assert provider.commands == []
    provider.update((*PEOPLE, Participant("4", "dave")))
    dave.update(DISCONNECTED)
    assert strip.text == ["Dave", "100%"]
    assert not dave.absent(DISCONNECTED)


def test_the_volume_range_is_the_one_of_the_other_strips_by_default(
    surface: RecordingSurface, env: StripEnv, provider: FakeProvider
):
    config = VoipStripConfig(type="voip")
    assert config.max_volume is None
    _, (strip,), _ = make(surface, env, provider, config)
    assert strip.max_volume == env.behavior.max_volume
