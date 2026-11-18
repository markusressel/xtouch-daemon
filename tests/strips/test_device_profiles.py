"""
Device strips that switch the profile of the sound card (Rec).
"""

import asyncio

import pytest

from tests.support.audio import FakeBackend, output
from tests.support.hardware import RecordingSurface
from tests.support.strips import make
from tests.support.tasks import settle
from xtouch_daemon.audio.model import AudioState, Card, Direction, Profile
from xtouch_daemon.config.audio_strips import ProfileConfig
from xtouch_daemon.config.values import Indicator
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Led
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.device import DeviceStrip

ANALOG = Profile("output:analog-stereo", "Analog Stereo Output")


DIGITAL = Profile("output:iec958-stereo", "Digital Stereo (IEC958) Output")


PROFILES = (
    ProfileConfig(label="Phones", profile="output:analog-stereo"),
    ProfileConfig(label="Speaker", profile=DIGITAL.description),
)


def on_card(profile: Profile, default: bool = True, volume: int = 50) -> AudioState:
    """The onboard card in `profile`: its output is the one of that profile."""
    name = f"alsa_output.pci.{profile.name.removeprefix('output:')}"
    return AudioState(
        outputs=(output(name, volume, card="alsa_card.pci"), output("buds", 30)),
        cards=(Card("alsa_card.pci", profile.name, (ANALOG, DIGITAL, Profile("off", "Off"))),),
        default_output=name if default else "buds",
    )


def make_with_profiles(
    surface: RecordingSurface,
    env: StripEnv,
    indicators: dict[Button, Indicator] | None = None,
    label: str | None = None,
) -> DeviceStrip:
    return make(surface, env, device="alsa_output.pci.*", label=label, profiles=PROFILES, indicators=indicators)


async def test_rec_switches_to_the_next_profile_and_its_label_names_the_strip(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_with_profiles(surface, env, indicators={Button.REC: "recording"})
    strip.update(on_card(ANALOG))
    s = surface.strips[0]
    assert s.text == ["Phones", "50%"]
    # the first profile: the LED is off (it shows the profile, not what records)
    assert s.leds[Button.REC] == Led.OFF

    strip.on_button(Button.REC, True)
    await settle()
    assert backend.calls == [("set_card_profile", "alsa_card.pci", "output:iec958-stereo")]
    # right away
    assert s.text[0] == "Speaker"

    # between the profiles, the card has no output for a moment
    strip.update(AudioState(cards=on_card(ANALOG).cards))
    assert s.text == ["Speaker", "off"]

    strip.update(on_card(DIGITAL, volume=70))
    await surface.settled()
    assert s.leds[Button.REC] == Led.ON
    assert s.text == ["Speaker", "70%"]
    assert surface.faders(0)[-1] == protocol.fader_value(0.7)

    strip.on_button(Button.REC, True)
    await settle()
    assert backend.calls[-1] == ("set_card_profile", "alsa_card.pci", "output:analog-stereo")
    # a release does nothing
    strip.on_button(Button.REC, False)
    await settle()
    assert len(backend.calls) == 2


async def test_without_a_profile_of_the_list_the_label_is_the_configured_one(
    surface: RecordingSurface, env: StripEnv
) -> None:
    surround = Profile("output:analog-surround-51", "Analog Surround 5.1 Output")
    state = on_card(ANALOG)
    other = AudioState(outputs=state.outputs, cards=(Card("alsa_card.pci", surround.name, (ANALOG, surround)),))
    make_with_profiles(surface, env, label="Onboard").update(other)
    assert surface.strips[0].text[0] == "Onboard"

    make_with_profiles(surface, env).update(other)
    assert surface.strips[0].text[0] == "alsa_ou"


async def test_the_new_output_becomes_the_default_if_the_old_one_was(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_with_profiles(surface, env)
    strip.update(on_card(ANALOG))
    strip.on_button(Button.REC, True)
    await settle()

    # the sound server made another output the default meanwhile
    strip.update(on_card(ANALOG, default=False))
    strip.update(on_card(DIGITAL, default=False))
    await settle()
    assert backend.calls[-1] == ("set_default", Direction.OUTPUT, "alsa_output.pci.iec958-stereo")

    # only once
    strip.update(on_card(DIGITAL, default=False))
    await settle()
    assert len(backend.calls) == 2


async def test_a_new_output_that_is_the_default_already_is_left_alone(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_with_profiles(surface, env)
    strip.update(on_card(ANALOG))
    strip.on_button(Button.REC, True)
    await settle()
    strip.update(on_card(DIGITAL))
    strip.update(on_card(DIGITAL, default=False))
    await settle()
    assert backend.calls == [("set_card_profile", "alsa_card.pci", "output:iec958-stereo")]


async def test_a_switch_from_an_output_that_is_not_the_default_changes_no_default(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_with_profiles(surface, env)
    strip.update(on_card(ANALOG, default=False))
    strip.on_button(Button.REC, True)
    await settle()
    strip.update(on_card(DIGITAL, default=False))
    await settle()
    assert backend.calls == [("set_card_profile", "alsa_card.pci", "output:iec958-stereo")]


async def test_a_failed_switch_is_logged_and_changes_no_default_later(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    backend.failing.add("set_card_profile")
    strip = make_with_profiles(surface, env)
    strip.update(on_card(ANALOG))
    strip.on_button(Button.REC, True)
    await settle()
    assert "Strip 1: switch to Speaker: set_card_profile failed" in caplog.text
    # back to the profile the card is in
    assert surface.strips[0].text[0] == "Phones"

    # switched some other way later
    strip.update(on_card(DIGITAL, default=False))
    await settle()
    assert len(backend.calls) == 1


async def test_a_card_in_another_profile_switches_to_the_first(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make_with_profiles(surface, env)
    surround = Profile("output:analog-surround-51", "Analog Surround 5.1 Output")
    state = on_card(ANALOG)
    strip.update(AudioState(outputs=state.outputs, cards=(Card("alsa_card.pci", surround.name, (ANALOG, surround)),)))
    assert surface.strips[0].leds[Button.REC] == Led.OFF

    strip.on_button(Button.REC, True)
    await settle()
    assert backend.calls == [("set_card_profile", "alsa_card.pci", "output:analog-stereo")]


async def test_a_profile_the_card_does_not_have_is_logged(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make_with_profiles(surface, env)
    state = on_card(ANALOG)
    strip.update(AudioState(outputs=state.outputs, cards=(Card("alsa_card.pci", ANALOG.name, (ANALOG,)),)))

    strip.on_button(Button.REC, True)
    await settle()
    assert backend.calls == []
    assert "Strip 1: alsa_card.pci has no profile 'Digital Stereo (IEC958) Output'" in caplog.text


async def test_rec_does_nothing_without_a_card(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env, device="buds", profiles=PROFILES)
    strip.update(on_card(ANALOG))
    strip.on_button(Button.REC, True)
    await settle()
    assert backend.calls == []
    assert surface.strips[0].leds[Button.REC] == Led.OFF


async def test_without_profiles_rec_shows_its_indicator(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env, device="alsa_output.pci.*", indicators={Button.REC: "default"})
    strip.update(on_card(DIGITAL))
    strip.on_button(Button.REC, True)
    await settle()
    assert backend.calls == []
    assert surface.strips[0].leds[Button.REC] == Led.ON


async def test_a_failed_switch_leaves_a_later_one_alone(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    backend.failing.add("set_card_profile")
    backend.gate = asyncio.Event()
    strip = make_with_profiles(surface, env)
    strip.update(on_card(ANALOG))
    strip.on_button(Button.REC, True)
    strip.on_button(Button.REC, True)
    await settle()
    assert surface.strips[0].text[0] == "Speaker"

    backend.gate.set()
    await settle()
    # both failed: the card is still in the first profile
    assert len(backend.calls) == 2
    assert surface.strips[0].text[0] == "Phones"


async def test_a_profile_has_a_volume_range_of_its_own(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    profiles = (PROFILES[0], ProfileConfig(label="Speaker", profile=DIGITAL.name, min_volume=50, max_volume=200))
    strip = make(surface, env, device="alsa_output.pci.*", profiles=profiles, max_volume=120)
    strip.update(on_card(ANALOG))
    strip.on_fader(1.0)
    await settle()
    # the range of the strip
    assert backend.calls[-1][3] == 120

    strip.on_button(Button.REC, True)
    await settle()
    strip.update(on_card(DIGITAL))
    strip.on_fader(1.0)
    await settle()
    assert backend.calls[-1][3] == 200
    strip.on_fader(0.0)
    await settle()
    assert backend.calls[-1][3] == 50
