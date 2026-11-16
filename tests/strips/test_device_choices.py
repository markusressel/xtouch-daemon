"""
Device strips with choices: Select steps through them, with the profile they need.
"""

import asyncio

import pytest

from tests.support.audio import FakeBackend, output
from tests.support.hardware import RecordingSurface
from tests.support.strips import STATE, make
from tests.support.tasks import settle
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Card, Direction, Profile
from xtouch_daemon.config.audio_strips import ChoiceConfig
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.device import ChoiceStrip, _options

CARD = "alsa_card.pci-0000_11_00.4"


PHONES_PROFILE = Profile("output:analog-stereo+input:analog-stereo", "Analog Stereo Output + Analog Stereo Input")


SPEAKER_PROFILE = Profile("output:iec958-stereo+input:analog-stereo", "Digital Stereo (IEC958) Output + Analog Input")


PHONES = "alsa_output.pci-0000_11_00.4.analog-stereo"


SPEAKER = "alsa_output.pci-0000_11_00.4.iec958-stereo"


BUDS = "bluez_output.AA_BB.1"


CHOICES = (
    ChoiceConfig(label="Phones", device=PHONES, card=CARD, profile=PHONES_PROFILE.name),
    # by the description of the card and of the profile
    ChoiceConfig(
        label="Speaker", device=SPEAKER, card="Family 17h*", profile=SPEAKER_PROFILE.description, max_volume=200
    ),
    ChoiceConfig(label="Buds", device="bluez_output.*"),
)


def sound(
    profile: Profile = PHONES_PROFILE, default: str | None = PHONES, buds: bool = True, volume: int = 50
) -> AudioState:
    """The onboard card in `profile` (its output is the one of the profile), and maybe Bluetooth headphones."""
    device = PHONES if profile == PHONES_PROFILE else SPEAKER
    return AudioState(
        outputs=(output(device, volume, card=CARD), *((output(BUDS, 30),) if buds else ())),
        cards=(Card(CARD, profile.name, (PHONES_PROFILE, SPEAKER_PROFILE), "Family 17h/19h HD Audio Controller"),),
        default_output=default,
    )


def make_choices(
    surface: RecordingSurface, env: StripEnv, choices: tuple[ChoiceConfig, ...] = CHOICES, **kwargs: object
) -> ChoiceStrip:
    return ChoiceStrip(surface.strips[0], env, Direction.OUTPUT, choices, color=Color.CYAN, **kwargs)  # type: ignore[arg-type]


async def test_the_choice_of_the_default_shows_with_its_label_and_range(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = make_choices(surface, env)
    strip.update(sound(SPEAKER_PROFILE, default=SPEAKER, volume=150))

    s = surface.strips[0]
    assert s.text == ["Speaker", "150%"]
    assert strip.volume_range() == (0, 200)
    assert s.leds[Button.SELECT] == Led.ON
    assert strip.available == (0, 1, 2)
    assert strip.meter_targets(sound(SPEAKER_PROFILE, default=SPEAKER)) == {CaptureTarget(SPEAKER, monitor=True)}
    assert not strip.absent(sound())

    strip.update(sound(default=BUDS))
    assert s.text == ["Buds", "30%"]
    # the range of the strip
    assert strip.volume_range() == (0, 100)


async def test_select_cycles_through_the_choices_with_the_profile_first(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_choices(surface, env)
    s = surface.strips[0]
    strip.update(sound())
    assert s.text[0] == "Phones"

    strip.on_button(Button.SELECT, True)
    await settle()
    # the card first, the label at once
    assert backend.calls == [("set_card_profile", CARD, SPEAKER_PROFILE.name)]
    assert s.text[0] == "Speaker"
    # the card switches: for a moment its output is gone, then the one of the profile is there
    strip.update(AudioState(cards=sound().cards, default_output=None))
    assert s.text[0] == "Speaker"
    strip.update(AudioState(cards=sound(SPEAKER_PROFILE).cards, default_output=None))
    assert s.text == ["Speaker", "off"]
    strip.update(sound(SPEAKER_PROFILE, default=BUDS))
    await settle()
    assert backend.calls[-1] == ("set_default", Direction.OUTPUT, SPEAKER)
    assert s.text[0] == "Speaker"
    strip.update(sound(SPEAKER_PROFILE, default=SPEAKER))
    assert s.leds[Button.SELECT] == Led.ON

    strip.on_button(Button.SELECT, True)
    await settle()
    # no profile: only the default
    assert backend.calls[-1] == ("set_default", Direction.OUTPUT, BUDS)
    strip.update(sound(SPEAKER_PROFILE, default=BUDS))
    assert s.text[0] == "Buds"

    strip.on_button(Button.SELECT, True)
    await settle()
    # around to the first one
    assert backend.calls[-1] == ("set_card_profile", CARD, PHONES_PROFILE.name)
    assert s.text[0] == "Phones"
    strip.update(sound(PHONES_PROFILE, default=BUDS))
    await settle()
    assert backend.calls[-1] == ("set_default", Direction.OUTPUT, PHONES)
    assert len(backend.calls) == 5


async def test_two_choices_in_the_same_profile_only_change_the_default(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    line_out = "alsa_output.pci-0000_11_00.4.analog-stereo-2"
    choices = (
        CHOICES[0],
        ChoiceConfig(label="Line", device=line_out, card=CARD, profile=PHONES_PROFILE.name),
    )
    strip = make_choices(surface, env, choices)
    state = sound(buds=False)
    strip.update(
        AudioState(outputs=(*state.outputs, output(line_out, card=CARD)), cards=state.cards, default_output=PHONES)
    )
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls == [("set_default", Direction.OUTPUT, line_out)]
    assert surface.strips[0].text[0] == "Line"


async def test_a_failed_switch_goes_back(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make_choices(surface, env)
    s = surface.strips[0]
    strip.update(sound())
    backend.failing = {"set_card_profile"}

    strip.on_button(Button.SELECT, True)
    assert s.text[0] == "Speaker"
    await settle()
    assert s.text[0] == "Phones"
    assert "switch to Speaker: set_card_profile failed" in caplog.text

    # a default that fails goes back as well
    backend.failing = {"set_default"}
    strip.update(sound(default=BUDS))
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls[-1] == ("set_default", Direction.OUTPUT, PHONES)
    assert s.text[0] == "Buds"


async def test_a_failure_of_a_switch_that_was_overtaken_changes_nothing(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_choices(surface, env)
    strip.update(sound())
    backend.gate = asyncio.Event()
    backend.failing = {"set_card_profile"}
    strip.on_button(Button.SELECT, True)
    strip.on_button(Button.SELECT, True)
    backend.gate.set()
    await settle()
    assert surface.strips[0].text[0] == "Buds"


async def test_a_press_during_a_switch_goes_on_from_where_it_goes(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_choices(surface, env)
    s = surface.strips[0]
    strip.update(sound())
    backend.gate = asyncio.Event()

    strip.on_button(Button.SELECT, True)
    strip.on_button(Button.SELECT, True)
    assert s.text[0] == "Buds"
    backend.gate.set()
    await settle()
    assert backend.calls == [
        ("set_card_profile", CARD, SPEAKER_PROFILE.name),
        ("set_default", Direction.OUTPUT, BUDS),
    ]
    # the card arrives in the profile of the choice it went past: that one does not become the default
    strip.update(sound(SPEAKER_PROFILE, default=None))
    await settle()
    assert len(backend.calls) == 2
    strip.update(sound(SPEAKER_PROFILE, default=BUDS))
    assert s.text[0] == "Buds"


async def test_the_strip_follows_a_default_set_elsewhere(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make_choices(surface, env)
    s = surface.strips[0]
    strip.update(sound())
    # headphones that connect become the default
    strip.update(sound(default=BUDS))
    assert s.text[0] == "Buds"
    # a default that is none of them: the one shown last stays
    strip.update(sound(default="hdmi"))
    assert s.text[0] == "Buds"
    assert s.leds[Button.SELECT] == Led.OFF
    # which goes away: the first one there is
    strip.update(sound(default="hdmi", buds=False))
    assert s.text[0] == "Phones"


async def test_select_on_a_choice_that_is_not_the_default_makes_it_the_default(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_choices(surface, env)
    strip.update(sound(default="hdmi"))
    strip.on_button(Button.SELECT, True)
    strip.on_button(Button.SELECT, False)
    await settle()
    assert backend.calls == [("set_default", Direction.OUTPUT, PHONES)]


async def test_without_any_choice_there_the_strip_is_absent(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_choices(surface, env)
    nothing = AudioState(outputs=(output("hdmi"),), default_output="hdmi")
    strip.update(nothing)

    assert strip.absent(nothing)
    assert surface.strips[0].text == ["Output", "off"]
    assert strip.meter_targets(nothing) == set()
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls == []


async def test_the_label_of_a_choice_without_one(surface: RecordingSurface, env: StripEnv) -> None:
    choices = (ChoiceConfig(device=PHONES), ChoiceConfig(device="bluez_output.*", card=CARD, profile="a2dp"))
    strip = make_choices(surface, env, choices)
    strip.update(sound())
    # the start of the description
    assert surface.strips[0].text[0] == "alsa_ou"
    labelled = make_choices(surface, env, choices, label="Out")
    labelled.update(sound())
    assert surface.strips[0].text[0] == "Out"


async def test_a_switch_to_a_device_that_is_not_there_yet_shows_its_name(
    surface: RecordingSurface, env: StripEnv
) -> None:
    choices = (
        ChoiceConfig(device="bluez_output.*"),
        ChoiceConfig(device=SPEAKER, card=CARD, profile=SPEAKER_PROFILE.name),
    )
    strip = make_choices(surface, env, choices)
    strip.update(sound(default=BUDS))
    strip.on_button(Button.SELECT, True)
    assert surface.strips[0].text[0] == "alsa_ou"


async def test_a_card_that_goes_away_during_the_switch_ends_it(
    surface: RecordingSurface, env: StripEnv, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make_choices(surface, env)
    strip.update(sound())
    strip.on_button(Button.SELECT, True)
    strip.update(AudioState(outputs=(output(BUDS),), default_output=BUDS))
    assert f"{CARD} went away during the switch" in caplog.text
    assert surface.strips[0].text[0] == "Buds"


async def test_a_choice_whose_device_is_missing_in_its_profile_is_not_switched_to(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make_choices(surface, env, CHOICES[1:])
    # the card is in the profile of the speaker, but its output is not there
    state = sound(SPEAKER_PROFILE, default=BUDS)
    strip.update(AudioState(outputs=(output(BUDS),), cards=state.cards, default_output=BUDS))
    strip.choose(0)
    await settle()
    assert backend.calls == []
    assert "Speaker is not there" in caplog.text


def test_the_options_in_home_assistant_differ() -> None:
    choices = (ChoiceConfig(label="Out", device="a"), ChoiceConfig(label="Out", device="b"), ChoiceConfig(device="c"))
    assert _options(choices) == ("Out", "Out 2", "c")


async def test_the_new_default_may_come_before_the_command_returns(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_choices(surface, env)
    strip.update(sound(SPEAKER_PROFILE, default=SPEAKER))
    backend.gate = asyncio.Event()
    strip.on_button(Button.SELECT, True)
    await settle()
    strip.update(sound(SPEAKER_PROFILE, default=BUDS))
    # a press now goes on from the choice shown
    backend.gate.set()
    await settle()
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls[-1] == ("set_card_profile", CARD, PHONES_PROFILE.name)


async def test_a_device_strip_is_absent_while_none_of_its_devices_is_there(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = make(surface, env, device=("speaker", "buds"))
    assert not strip.absent(STATE)
    assert strip.absent(AudioState(outputs=(output("hdmi"),)))
    # the default device is never absent
    assert not make(surface, env, device=None).absent(AudioState())
    strip.update(STATE)
    assert strip.title == "buds de"
    nothing = make_choices(surface, env)
    nothing.update(AudioState())
    assert nothing.volume_range() == (0, 100)


async def test_without_home_assistant_a_strip_with_choices_has_no_entities(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = make_choices(surface, env)
    assert strip.entities == {}
    strip.close()
