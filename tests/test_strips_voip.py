import asyncio
from collections.abc import AsyncIterator

import pytest

from tests.conftest import RecordingSurface, finish_tasks, settle
from xtouch_daemon import protocol
from xtouch_daemon.audio.model import DISCONNECTED
from xtouch_daemon.config import VoipStripConfig
from xtouch_daemon.protocol import Button, Color, Led
from xtouch_daemon.strips import voip as voip_module
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.voip import VoipGroup, VoipStrip
from xtouch_daemon.voip import Capability, Participant, VoipProvider

CONFIG = VoipStripConfig(type="voip", count=2, color="cyan", talking_color="green", max_volume=200)


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


def make(surface: RecordingSurface, env: StripEnv, provider: VoipProvider, config: VoipStripConfig = CONFIG):
    refreshed: list[int] = []
    group = VoipGroup(provider, config.count, lambda: refreshed.append(1))
    strips = [VoipStrip(surface.strips[slot], env, group, slot, config) for slot in range(config.count)]
    return group, strips, refreshed


def test_the_pages_of_a_group(provider: FakeProvider):
    group = VoipGroup(provider, 2)
    assert group.pages == 2
    assert [group.participant(slot) for slot in (0, 1)] == list(PEOPLE[:2])
    assert group.next_page() == "pg 2/2"
    assert [group.participant(slot) for slot in (0, 1)] == [PEOPLE[2], None]
    assert group.next_page() == "pg 1/2"
    group.page = 1
    provider.update(PEOPLE[:1])
    # fewer participants: the page wraps
    assert group.pages == 1
    assert group.participant(0) == PEOPLE[0]
    assert VoipGroup(FakeProvider(), 3).pages == 1


async def test_a_strip_shows_its_participant(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    _, (ann, bob), _ = make(surface, env, provider)
    ann.update(DISCONNECTED)
    bob.update(DISCONNECTED)
    await settle()
    first, second = surface.strips[:2]
    assert (first.color, first.text, first.leds[Button.MUTE]) == (Color.GREEN, ["Annabel", "100%"], Led.OFF)
    assert first.fader == protocol.fader_value(0.5)
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
    _, (ann, _), _ = make(surface, env, provider, CONFIG.model_copy(update={"meter": False}))
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
    assert provider.commands == [("volume", "1", 50)]
    assert surface.strips[0].text[1] == "50%"
    # until the provider tells it, the strip shows what the fader set
    ann.update(DISCONNECTED)
    assert surface.strips[0].text[1] == "50%"
    ann.on_touch(False)
    provider.update((Participant("1", "Annabelle", volume=50), *PEOPLE[1:]))
    ann.update(DISCONNECTED)
    assert surface.strips[0].text[1] == "50%"
    assert ann._wanted is None  # pyright: ignore[reportPrivateUsage]
    ann.on_fader(0.25)
    await settle()
    assert provider.commands == [("volume", "1", 50)]


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
    group, (ann, bob), refreshed = make(surface, env, provider)
    bob.on_button(Button.SELECT, True)
    bob.on_button(Button.SELECT, False)
    assert group.page == 1
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
