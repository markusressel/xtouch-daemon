import asyncio

import pytest

from tests.support.audio import FakeBackend, output, source
from tests.support.hardware import RecordingSurface
from tests.support.tasks import settle
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Card, Direction, Profile
from xtouch_daemon.config.audio_strips import ChoiceConfig, ProfileConfig
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import Indicator
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.strips.base import StripEnv, fader_position, fader_volume
from xtouch_daemon.strips.device import ChoiceStrip, DeviceStrip, _options


def make(
    surface: RecordingSurface,
    env: StripEnv,
    direction: Direction = Direction.OUTPUT,
    device: str | tuple[str, ...] | None = "speaker",
    **kwargs: object,
) -> DeviceStrip:
    devices = () if device is None else (device,) if isinstance(device, str) else device
    return DeviceStrip(surface.strips[0], env, direction, devices, color=Color.CYAN, **kwargs)  # type: ignore[arg-type]


STATE = AudioState(
    outputs=(output("speaker", 50), output("buds", 30, running=True)),
    inputs=(source("mic", 80),),
    default_output="buds",
    default_input="mic",
)


async def test_the_volume_shows_on_fader_lcd_and_ring(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, label="Speaker")
    strip.update(STATE)
    await surface.settled()

    s = surface.strips[0]
    assert surface.faders(0)[-1] == protocol.fader_value(0.5)
    assert s.text == ["Speaker", "50%"]
    assert s.ring == (6, RingMode.WRAP)
    assert s.color == Color.CYAN
    assert s.leds[Button.MUTE] == Led.OFF


async def test_a_muted_device_says_so(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env)
    strip.update(AudioState(outputs=(output("speaker", 50, muted=True),)))

    assert surface.strips[0].text[1] == "muted"
    assert surface.strips[0].leds[Button.MUTE] == Led.ON


async def test_the_label_defaults_to_the_start_of_the_description(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env)
    assert strip.label == "Output"

    strip.update(STATE)
    assert surface.strips[0].text[0] == "speaker"


async def test_the_default_device_strip_follows_the_default(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device=None)
    strip.update(STATE)
    assert surface.strips[0].text == ["Output", "30%"]

    strip.update(AudioState(outputs=STATE.outputs, default_output="speaker"))
    assert surface.strips[0].text == ["Output", "50%"]
    # a default strip has nothing to select
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF


async def test_an_input_strip_is_labelled_input(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, Direction.INPUT, None)
    strip.update(STATE)
    assert surface.strips[0].text == ["Input", "80%"]


async def test_a_missing_device_is_dark_off_and_ignores_the_fader(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env, device="gone", label="Buds")
    strip.update(STATE)
    await surface.settled()

    s = surface.strips[0]
    assert s.color == Color.BLACK
    assert s.text == ["Buds", "off"]
    assert surface.faders(0)[-1] == 0
    assert s.ring == (0, RingMode.DOT)

    strip.on_fader(0.5)
    strip.on_encoder(3)
    strip.on_encoder_press(True)
    strip.on_button(Button.MUTE, True)
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls == []


async def test_without_a_sound_server_every_device_is_off(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device=None)
    strip.update(DISCONNECTED)
    assert surface.strips[0].text[1] == "off"


async def test_the_fader_sets_the_volume(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_fader(0.42)
    await settle()

    assert backend.calls == [("set_device_volume", Direction.OUTPUT, "speaker", 42)]
    assert surface.strips[0].text[1] == "42%"


async def test_fast_fader_moves_set_only_the_latest_volume(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    gate = backend.gate = asyncio.Event()

    strip.on_fader(0.10)
    await settle()
    strip.on_fader(0.20)
    strip.on_fader(0.30)
    gate.set()
    await settle()

    assert [call[3] for call in backend.calls] == [10, 30]


async def test_the_volume_set_stays_shown_until_the_sound_server_reports_it(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_fader(0.7)
    await settle()

    assert surface.strips[0].text[1] == "70%"


async def test_a_failing_volume_command_is_logged(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    backend.failing.add("set_device_volume")

    strip.on_fader(0.7)
    await settle()

    assert "set_device_volume failed" in caplog.text
    # the strip shows the volume it knows again
    assert surface.strips[0].text[1] == "50%"


async def test_the_encoder_changes_the_volume_in_steps_and_moves_the_fader(
    surface: RecordingSurface, backend: FakeBackend
) -> None:
    env = StripEnv(backend, BehaviorConfig(max_volume=100, encoder_step=2))
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_encoder(3)
    await settle()
    strip.on_encoder(-1)
    await settle()
    await surface.settled()

    assert [call[3] for call in backend.calls] == [56, 54]
    assert surface.faders(0)[-1] == protocol.fader_value(0.54)


async def test_the_encoder_does_not_go_beyond_the_limits(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(AudioState(outputs=(output("speaker", 99),)))

    strip.on_encoder(5)
    await settle()

    assert backend.calls[-1][3] == 100


async def test_a_push_on_the_encoder_resets_the_volume(surface: RecordingSurface, backend: FakeBackend) -> None:
    env = StripEnv(backend, BehaviorConfig(max_volume=100, reset_volume=80))
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_encoder_press(False)
    strip.on_encoder_press(True)
    await settle()

    assert backend.calls == [("set_device_volume", Direction.OUTPUT, "speaker", 80)]


async def test_above_100_percent_the_fader_covers_the_amplification(
    surface: RecordingSurface, backend: FakeBackend
) -> None:
    env = StripEnv(backend, BehaviorConfig(max_volume=150))
    strip = make(surface, env)
    strip.update(AudioState(outputs=(output("speaker", 150),)))
    await surface.settled()
    assert surface.faders(0)[-1] == protocol.FADER_MAX

    # below the 0 dB mark up to 100 %
    strip.on_fader(0.5)
    await settle()
    assert backend.calls[-1][3] == 65


def test_100_percent_sits_at_the_unity_mark_of_the_fader() -> None:
    # 0..100 % below the mark at 77 % of the travel, 100..130 % above it
    assert [round(fader_volume(f, 0, 130, 77), 1) for f in (0.0, 0.385, 0.77, 0.885, 1.0)] == [0, 50, 100, 115, 130]
    assert [round(fader_position(v, 0, 130, 77), 3) for v in (0, 50, 100, 115, 130, 300)] == [
        0,
        0.385,
        0.77,
        0.885,
        1,
        1,
    ]
    # the range of the strip on both sides
    assert fader_volume(0.0, 50, 200, 77) == 50
    assert fader_volume(0.77, 50, 200, 77) == pytest.approx(100)
    assert fader_position(-5, 50, 200, 77) == 0
    # linear for ranges that do not go across 100 %
    assert fader_volume(0.5, 0, 100, 77) == 50
    assert fader_volume(0.5, 100, 200, 77) == 150
    assert fader_position(150, 100, 200, 77) == 0.5


async def test_the_fader_of_a_strip_above_100_percent_has_100_at_the_mark(
    surface: RecordingSurface, backend: FakeBackend
) -> None:
    env = StripEnv(backend, BehaviorConfig(max_volume=130, unity_at=77))
    strip = make(surface, env)
    strip.update(AudioState(outputs=(output("speaker", 100),)))
    await surface.settled()
    assert surface.faders(0)[-1] == protocol.fader_value(0.77)
    assert surface.strips[0].ring == (round(0.77 * (protocol.RING_MAX - 1)) + 1, RingMode.WRAP)

    strip.on_fader(0.385)
    await settle()
    assert backend.calls[-1][3] == 50
    strip.on_fader(1.0)
    await settle()
    assert backend.calls[-1][3] == 130


async def test_a_strip_has_a_volume_range_of_its_own(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env, min_volume=50, max_volume=200)
    strip.update(AudioState(outputs=(output("speaker", 125),)))
    await surface.settled()
    s = surface.strips[0]
    # a quarter of the way from the 0 dB mark (100 %) to the top
    assert surface.faders(0)[-1] == protocol.fader_value(0.77 + 0.25 * 0.23)
    assert s.ring == (round(0.8275 * (protocol.RING_MAX - 1)) + 1, RingMode.WRAP)

    strip.on_fader(0.0)
    await settle()
    assert backend.calls[-1][3] == 50
    strip.on_fader(1.0)
    await settle()
    assert backend.calls[-1][3] == 200

    # the encoder stays in the range, the reset volume too
    strip.update(AudioState(outputs=(output("speaker", 199),)))
    strip.on_encoder(5)
    await settle()
    assert backend.calls[-1][3] == 200
    strip.update(AudioState(outputs=(output("speaker", 52),)))
    strip.on_encoder(-5)
    await settle()
    assert backend.calls[-1][3] == 50

    # below the range, the fader is at the bottom
    strip.update(AudioState(outputs=(output("speaker", 20),)))
    await surface.settled()
    assert surface.faders(0)[-1] == 0
    assert s.text[1] == "20%"


async def test_a_push_on_the_encoder_resets_within_the_range(surface: RecordingSurface, backend: FakeBackend) -> None:
    env = StripEnv(backend, BehaviorConfig(max_volume=100, reset_volume=100))
    strip = make(surface, env, max_volume=80)
    strip.update(STATE)
    strip.on_encoder_press(True)
    await settle()
    assert backend.calls == [("set_device_volume", Direction.OUTPUT, "speaker", 80)]


async def test_mute_toggles_mute(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_button(Button.MUTE, True)
    strip.on_button(Button.MUTE, False)
    await settle()
    strip.update(AudioState(outputs=(output("speaker", 50, muted=True),)))
    strip.on_button(Button.MUTE, True)
    await settle()

    assert backend.calls == [
        ("set_device_mute", Direction.OUTPUT, "speaker", True),
        ("set_device_mute", Direction.OUTPUT, "speaker", False),
    ]


async def test_select_makes_the_device_the_default_and_its_led_shows_it(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF

    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls == [("set_default", Direction.OUTPUT, "speaker")]

    strip.update(AudioState(outputs=STATE.outputs, default_output="speaker"))
    assert surface.strips[0].leds[Button.SELECT] == Led.ON


async def test_select_can_be_switched_off(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env, select=False)
    strip.update(AudioState(outputs=STATE.outputs, default_output="speaker"))

    strip.on_button(Button.SELECT, True)
    await settle()

    assert backend.calls == []
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF


async def test_a_failing_command_is_logged(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    backend.failing.add("set_default")

    strip.on_button(Button.SELECT, True)
    await settle()

    assert "Strip 1: make default: set_default failed" in caplog.text


async def test_the_meter_shows_the_monitor_of_an_output_or_the_input(surface: RecordingSurface, env: StripEnv) -> None:
    out = make(surface, env)
    mic = make(surface, env, Direction.INPUT, "mic")

    assert out.meter_targets(STATE) == {CaptureTarget("speaker", monitor=True)}
    assert mic.meter_targets(STATE) == {CaptureTarget("mic", monitor=False)}
    assert make(surface, env, device="gone").meter_targets(STATE) == set()
    assert make(surface, env, meter=False).meter_targets(STATE) == set()


async def test_the_meters_can_be_switched_off_for_all_strips(surface: RecordingSurface, backend: FakeBackend) -> None:
    env = StripEnv(backend, BehaviorConfig(max_volume=100, meters=False))
    assert make(surface, env).meter_targets(STATE) == set()


async def test_a_device_plays_while_it_runs(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device="buds")

    assert strip.is_playing(CaptureTarget("buds", True), STATE)
    assert not strip.is_playing(CaptureTarget("speaker", True), STATE)
    assert not strip.is_playing(CaptureTarget("gone", True), STATE)


async def test_closing_stops_running_commands(surface: RecordingSurface, env: StripEnv, backend: FakeBackend) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    backend.gate = asyncio.Event()
    strip.on_button(Button.MUTE, True)
    await settle()

    strip.close()
    await settle()

    assert all(task.done() for task in strip._tasks)


async def test_a_device_that_went_away_gets_no_queued_volume(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)
    gate = backend.gate = asyncio.Event()
    strip.on_fader(0.1)
    await settle()
    strip.on_fader(0.2)
    # the set volume shows while the command runs, even when a state comes in between
    strip.update(STATE)
    assert surface.strips[0].text[1] == "20%"

    strip.update(AudioState())
    gate.set()
    await settle()

    assert backend.calls == [("set_device_volume", Direction.OUTPUT, "speaker", 10)]


async def test_a_device_that_went_away_gets_no_mute(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env)
    strip.update(STATE)

    strip.on_button(Button.MUTE, True)
    strip.update(AudioState())
    await settle()

    assert backend.calls == []


REC_SOLO = {Button.REC: "recording", Button.SOLO: "playing"}


async def test_the_rec_led_shows_whether_an_application_records_the_device(
    surface: RecordingSurface, env: StripEnv
) -> None:
    from xtouch_daemon.audio.model import Capture

    mic = make(surface, env, Direction.INPUT, "mic", indicators=REC_SOLO)
    discord = Capture(5, "Discord", "discord", "mic", Direction.INPUT, corked=False)

    mic.update(AudioState(inputs=STATE.inputs, captures=(discord,)))
    assert surface.strips[0].leds[Button.REC] == Led.ON

    mic.update(AudioState(inputs=STATE.inputs))
    assert surface.strips[0].leds[Button.REC] == Led.OFF


@pytest.mark.parametrize(
    ("indicator", "device", "lit"),
    [
        ("playing", "buds", True),
        ("playing", "speaker", False),
        ("default", "buds", True),
        ("default", "speaker", False),
        ("muted", "speaker", False),
        ("off", "buds", False),
        ("recording", "buds", False),
        # a device that is not there shows nothing
        ("playing", "gone", False),
        ("default", "gone", False),
        ("muted", "gone", False),
    ],
)
async def test_leds_show_what_they_are_set_to(
    surface: RecordingSurface, env: StripEnv, indicator: str, device: str, lit: bool
) -> None:
    strip = make(surface, env, device=device, indicators={Button.SOLO: indicator})
    strip.update(STATE)

    assert surface.strips[0].leds[Button.SOLO] == (Led.ON if lit else Led.OFF)


async def test_the_muted_indicator(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, indicators={Button.SOLO: "muted"})
    strip.update(AudioState(outputs=(output("speaker", 50, muted=True),)))

    assert surface.strips[0].leds[Button.SOLO] == Led.ON


async def test_leds_without_indicator_are_left_alone(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env)
    surface.strips[0].set_led(Button.REC, Led.FLASH)
    strip.update(STATE)

    assert surface.strips[0].leds[Button.REC] == Led.FLASH


# -- several devices ----------------------------------------------------------------------------------------------

HEADPHONES = AudioState(
    outputs=(output("speaker", 50), output("bluez_output.a", 30), output("bluez_output.b", 70)),
    default_output="speaker",
)


async def test_of_several_devices_the_first_one_there_shows(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device=("bluez_output.gone", "bluez_output.*"))
    strip.update(HEADPHONES)

    assert strip.device is not None
    assert strip.device.name == "bluez_output.a"
    assert surface.strips[0].text == ["bluez_o", "30%"]
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF


async def test_the_default_one_shows_and_otherwise_the_one_shown_last(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device="bluez_output.*")
    strip.update(AudioState(outputs=HEADPHONES.outputs, default_output="bluez_output.b"))
    assert strip.device is not None
    assert strip.device.name == "bluez_output.b"
    assert surface.strips[0].leds[Button.SELECT] == Led.ON

    # the speaker became the default again: the strip stays with the headphones it showed
    strip.update(HEADPHONES)
    assert strip.device.name == "bluez_output.b"
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF

    # they were switched off
    strip.update(AudioState(outputs=HEADPHONES.outputs[:2], default_output="speaker"))
    assert strip.device.name == "bluez_output.a"


async def test_select_makes_the_one_shown_the_default_and_then_switches(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = make(surface, env, device="bluez_output.*")
    strip.update(HEADPHONES)

    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls == [("set_default", Direction.OUTPUT, "bluez_output.a")]

    strip.update(AudioState(outputs=HEADPHONES.outputs, default_output="bluez_output.a"))
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls[-1] == ("set_default", Direction.OUTPUT, "bluez_output.b")

    # and around
    strip.update(AudioState(outputs=HEADPHONES.outputs, default_output="bluez_output.b"))
    strip.on_button(Button.SELECT, True)
    await settle()
    assert backend.calls[-1] == ("set_default", Direction.OUTPUT, "bluez_output.a")


async def test_the_meter_follows_the_device_shown(surface: RecordingSurface, env: StripEnv) -> None:
    strip = make(surface, env, device="bluez_output.*")
    strip.update(AudioState(outputs=HEADPHONES.outputs, default_output="bluez_output.b"))

    assert strip.meter_targets(HEADPHONES) == {CaptureTarget("bluez_output.b", monitor=True)}


# -- profiles of the sound card ---------------------------------------------------------------------------------------

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


# -- choices ---------------------------------------------------------------------------------------------------------

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
