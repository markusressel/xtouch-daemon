import asyncio
from collections.abc import AsyncIterator

import pytest

from tests.support.hardware import RecordingSurface
from tests.support.tasks import finish_tasks, settle
from xtouch_daemon.audio.meter import CaptureTarget, Lit, Peak
from xtouch_daemon.audio.model import DISCONNECTED
from xtouch_daemon.config.voip_strips import VoipStripConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.strips import look_of
from xtouch_daemon.strips.base import Identity, StripEnv
from xtouch_daemon.strips.voip import VoipStrip
from xtouch_daemon.voip import Capability, Participant, VoipProvider

CONFIG = VoipStripConfig(type="voip", color="cyan", talking_color="green", max_volume=200)
ID = Identity("ann", "Ann")


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
    surface: RecordingSurface, env: StripEnv, provider: VoipProvider, *configs: VoipStripConfig
) -> list[VoipStrip]:
    """Strips of people with these configurations (by default Annabelle and Bob) on the first strips of the surface."""
    configs = configs or (fixed("Annabelle"), fixed("Bob"))
    return [
        VoipStrip(surface.strips[index], env, ID, look_of(config), provider, config)
        for index, config in enumerate(configs)
    ]


def fixed(*names: str, **options: object) -> VoipStripConfig:
    return CONFIG.model_copy(update={"person": names, **options})


async def test_a_person_has_names_ignoring_case(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    (carol,) = make(surface, env, provider, fixed("Carol", "carol-phone"))
    assert carol.participant == PEOPLE[2]
    phone = Participant("4", "CAROL-PHONE")
    provider.update((phone, *PEOPLE))
    # the first one of the names in the order of the provider
    assert carol.participant == phone
    provider.update(PEOPLE[:2])
    assert carol.participant is None
    # no wildcards, no parts of a name
    (caro,) = make(surface, env, provider, fixed("caro"))
    provider.update(PEOPLE)
    assert caro.participant is None


def test_a_strip_of_the_voice_chat_shows_a_person(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    with pytest.raises(AssertionError, match="shows a person"):
        make(surface, env, provider, CONFIG)


async def test_a_strip_shows_its_participant(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    ann, bob = make(surface, env, provider)
    ann.update(DISCONNECTED)
    bob.update(DISCONNECTED)
    await settle()
    first, second = surface.strips[:2]
    assert (first.color, first.text, first.leds[Button.MUTE]) == (Color.GREEN, ["Annabel", "100%"], Led.OFF)
    # 100 % at the 0 dB mark (`behavior.unity_at`), as on the other strips
    assert first.fader == protocol.fader_value(0.77)
    # Select does nothing on the strip of a person
    assert first.leds[Button.SELECT] == Led.OFF
    assert (second.color, second.text, second.leds[Button.MUTE]) == (Color.CYAN, ["Bob", "muted"], Led.ON)
    # audio: the mixer shows it in dB like the meters of streams
    assert ann.held_meter("pre_fader") == Peak(0.5)
    assert bob.held_meter("pre_fader") is None


async def test_the_meter_takes_the_voice_before_or_after_the_fader(
    surface: RecordingSurface, env: StripEnv, provider: FakeProvider
):
    provider.update(
        (
            Participant("1", "Ann", talking=True, volume=50, level=0.3, pre_fader_level=0.6),
            Participant("2", "Bob", talking=True, muted=True, level=0.0, pre_fader_level=0.0),
        )
    )
    ann, bob = make(surface, env, provider, fixed("Ann"), fixed("Bob"))
    assert ann.held_meter("pre_fader") == Peak(0.6)
    assert ann.held_meter("post_fader") == Peak(0.3)
    # the voice chat doesn't get the voice of a muted participant: before the fader they light it while they talk
    assert bob.held_meter("pre_fader") == Lit(protocol.METER_MAX - 1)
    assert bob.held_meter("post_fader") == Peak(0.0)
    # a plugin without the level before the fader: the one after it
    provider.update((Participant("1", "Ann", talking=True, level=0.3), Participant("2", "Bob", muted=True)))
    assert ann.held_meter("pre_fader") == Peak(0.3)
    assert bob.held_meter("pre_fader") is None


class TwoClients(FakeProvider):
    """Ann in a client that sets volumes and mutes, Bob in one that does neither."""

    def capabilities_of(self, participant_id: str) -> frozenset[Capability]:
        return frozenset(Capability) if participant_id.startswith("mumble:") else frozenset()


async def test_a_strip_can_what_the_client_of_its_person_can(surface: RecordingSurface, env: StripEnv):
    provider = TwoClients(frozenset(Capability))
    provider.update((Participant("mumble:1", "Ann", volume=50), Participant("other:1", "Bob", volume=50)))
    ann, bob = make(surface, env, provider, fixed("Ann"), fixed("Bob"))
    ann.update(DISCONNECTED)
    bob.update(DISCONNECTED)
    assert surface.strips[0].text == ["Ann", "50%"]
    assert surface.strips[1].text == ["Bob", ""]
    for strip in (ann, bob):
        strip.on_fader(0.9)
        strip.on_button(Button.MUTE, True)
    await settle()
    assert [command[1] for command in provider.commands] == ["mumble:1", "mumble:1"]
    # nobody there: what the provider can
    carol = make(surface, env, provider, fixed("Carol"))[0]
    assert carol.can(Capability.VOLUME)


async def test_without_volumes_and_levels(surface: RecordingSurface, env: StripEnv):
    provider = FakeProvider(frozenset())
    provider.update((Participant("1", "Ann", talking=True), Participant("2", "Bob")))
    ann, bob = make(surface, env, provider, fixed("Ann"), fixed("Bob"))
    ann.update(DISCONNECTED)
    bob.update(DISCONNECTED)
    assert surface.strips[0].text == ["Ann", "talks"]
    assert surface.strips[1].text == ["Bob", ""]
    assert surface.strips[0].fader == 0
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF
    # a talking participant fills the meter, a silent one leaves it
    assert ann.held_meter("pre_fader") == Lit(protocol.METER_MAX - 1)
    assert bob.held_meter("pre_fader") is None
    ann.on_fader(0.5)
    ann.on_button(Button.MUTE, True)
    await settle()
    assert provider.commands == []


async def test_the_meter_can_be_off(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    (ann,) = make(surface, env, provider, fixed("Annabelle", meter=False))
    assert ann.held_meter("pre_fader") is None


async def test_the_fader_sets_the_volume(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    ann, _ = make(surface, env, provider)
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
    ann, bob = make(surface, env, provider)
    ann.on_button(Button.MUTE, True)
    ann.on_button(Button.MUTE, False)
    bob.on_button(Button.MUTE, True)
    ann.on_button(Button.REC, True)
    await settle()
    assert provider.commands == [("muted", "1", True), ("muted", "2", False)]


async def test_a_strip_of_a_person(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    (carol,) = make(surface, env, provider, fixed("carol", label="Mum"))
    carol.update(DISCONNECTED)
    assert surface.strips[0].text == ["Mum", "150%"]
    assert carol.title == "Mum"
    carol.on_button(Button.SELECT, True)
    carol.on_fader(0.25)
    carol.on_button(Button.MUTE, True)
    await settle()
    assert provider.commands == [("volume", "3", 32), ("muted", "3", True)]


async def test_a_person_who_is_away(surface: RecordingSurface, env: StripEnv, provider: FakeProvider):
    (dave,) = make(surface, env, provider, fixed("Dave"))
    dave.update(DISCONNECTED)
    strip = surface.strips[0]
    # the name stays, dark, with the fader down
    assert (strip.color, strip.text, strip.fader) == (Color.BLACK, ["Dave", "away"], 0)
    assert strip.leds[Button.MUTE] == Led.OFF
    assert dave.title == "Dave"
    assert dave.held_meter("pre_fader") is None
    # people have no meter of the sound server
    assert dave.target_gain(CaptureTarget(None, monitor=True), DISCONNECTED) is None
    dave.on_fader(0.5)
    dave.on_button(Button.MUTE, True)
    await settle()
    assert provider.commands == []
    provider.update((*PEOPLE, Participant("4", "dave")))
    dave.update(DISCONNECTED)
    assert strip.text == ["Dave", "100%"]


def test_the_volume_range_is_the_one_of_the_other_strips_by_default(
    surface: RecordingSurface, env: StripEnv, provider: FakeProvider
):
    config = VoipStripConfig(type="voip", person=("Ann",))
    assert config.max_volume is None
    (strip,) = make(surface, env, provider, config)
    assert strip.max_volume == env.behavior.max_volume
