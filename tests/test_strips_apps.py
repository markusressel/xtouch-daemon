import asyncio

import pytest

from tests.conftest import FakeBackend, RecordingSurface, settle, stream
from xtouch_daemon import protocol
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Capture, Direction
from xtouch_daemon.config import BehaviorConfig
from xtouch_daemon.protocol import Button, Color, Led
from xtouch_daemon.strips.apps import AppGroupStrip, AutoAssigner, AutoStrip
from xtouch_daemon.strips.base import StripEnv

BROWSERS = ("brave", "firefox")


def group(surface: RecordingSurface, env: StripEnv, meter: bool = True) -> AppGroupStrip:
    return AppGroupStrip(surface.strips[0], env, BROWSERS, "Browser", Color.YELLOW, meter)


def state(*streams: object) -> AudioState:
    return AudioState(streams=streams)  # type: ignore[arg-type]


# -- application groups -------------------------------------------------------------------------------------------


async def test_a_group_without_streams_is_idle_and_dark(surface: RecordingSurface, env: StripEnv) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, "Spotify", "spotify")))
    await surface.settled()

    s = surface.strips[0]
    assert s.color == Color.BLACK
    assert s.text == ["Browser", "idle"]
    assert surface.faders(0)[-1] == 0


async def test_a_group_shows_its_loudest_stream(surface: RecordingSurface, env: StripEnv) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, "Brave", volume=80), stream(2, "Firefox", "firefox", volume=60)))
    await surface.settled()

    s = surface.strips[0]
    assert s.color == Color.YELLOW
    assert s.text == ["Browser", "80%"]
    assert surface.faders(0)[-1] == protocol.fader_value(0.8)


async def test_the_fader_sets_all_streams_of_the_group(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, volume=80), stream(2, "Firefox", "firefox", volume=60)))

    strip.on_fader(0.4)
    await settle()

    assert sorted(backend.calls) == [("set_stream_volume", 1, 40), ("set_stream_volume", 2, 40)]


async def test_a_new_stream_gets_the_volume_of_the_group(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, volume=40)))

    strip.update(state(stream(1, volume=40), stream(3, volume=100)))
    await settle()

    assert backend.calls == [("set_stream_volume", 3, 40)]
    assert surface.strips[0].text[1] == "40%"


async def test_an_idle_group_keeps_the_fader_volume_for_the_next_stream(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = group(surface, env)
    strip.update(state())

    strip.on_fader(0.25)
    await settle()
    assert backend.calls == []
    assert surface.strips[0].text[1] == "idle"

    strip.update(state(stream(7, volume=100)))
    await settle()
    assert backend.calls == [("set_stream_volume", 7, 25)]
    assert surface.strips[0].text[1] == "25%"


async def test_before_the_first_stream_a_new_stream_keeps_its_volume(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, volume=70)))
    await settle()

    assert backend.calls == []
    assert strip.group_volume == 70


async def test_a_volume_changed_elsewhere_is_followed(surface: RecordingSurface, env: StripEnv) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, volume=70)))
    strip.update(state(stream(1, volume=30)))

    assert surface.strips[0].text[1] == "30%"
    assert strip.group_volume == 30


async def test_the_group_shows_the_volume_it_keeps_while_idle(surface: RecordingSurface, env: StripEnv) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, volume=70)))
    strip.update(state())
    await surface.settled()

    assert surface.strips[0].text[1] == "idle"
    assert surface.faders(0)[-1] == protocol.fader_value(0.7)


async def test_mute_mutes_all_streams_unless_all_are_muted(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, muted=True), stream(2, "Firefox", "firefox")))
    assert surface.strips[0].leds[Button.MUTE] == Led.OFF

    strip.on_button(Button.MUTE, True)
    await settle()
    assert sorted(backend.calls) == [("set_stream_mute", 1, True), ("set_stream_mute", 2, True)]

    backend.calls.clear()
    strip.update(state(stream(1, muted=True), stream(2, "Firefox", "firefox", muted=True)))
    assert surface.strips[0].leds[Button.MUTE] == Led.ON
    assert surface.strips[0].text[1] == "muted"
    strip.on_button(Button.MUTE, True)
    await settle()
    assert sorted(backend.calls) == [("set_stream_mute", 1, False), ("set_stream_mute", 2, False)]


async def test_a_stream_that_fails_is_logged_and_the_others_still_set(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1), stream(2)))
    backend.failing.add("set_stream_volume")

    strip.on_fader(0.5)
    await settle()

    assert len(backend.calls) == 2
    assert "Browser: volume: set_stream_volume failed" in caplog.text


async def test_the_meter_shows_the_streams_of_the_group(surface: RecordingSurface, env: StripEnv) -> None:
    current = state(stream(1), stream(2, "Spotify", "spotify"), stream(3, "Firefox", "firefox", corked=True))

    assert group(surface, env).meter_targets(current) == {CaptureTarget("1", False), CaptureTarget("3", False)}
    assert group(surface, env, meter=False).meter_targets(current) == set()


async def test_a_stream_plays_while_it_is_not_paused(surface: RecordingSurface, env: StripEnv) -> None:
    strip = group(surface, env)
    current = state(stream(1), stream(3, corked=True))

    assert strip.is_playing(CaptureTarget("1", False), current)
    assert not strip.is_playing(CaptureTarget("3", False), current)
    assert not strip.is_playing(CaptureTarget("9", False), current)


# -- auto strips --------------------------------------------------------------------------------------------------


def auto(surface: RecordingSurface, env: StripEnv) -> AutoStrip:
    return AutoStrip(surface.strips[0], env, {"WEBRTC VoiceEngine": "Discord"}, Color.CYAN)


async def test_an_auto_strip_without_application_is_dark_and_empty(surface: RecordingSurface, env: StripEnv) -> None:
    strip = auto(surface, env)
    strip.update(state(stream(1)))

    assert surface.strips[0].text == ["", ""]
    assert surface.strips[0].color == Color.BLACK


async def test_an_auto_strip_shows_its_application_under_its_alias(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = auto(surface, env)
    strip.assign("WEBRTC VoiceEngine")
    strip.update(state(stream(1, "WEBRTC VoiceEngine", "Discord", volume=60), stream(2)))

    assert surface.strips[0].text == ["Discord", "60%"]
    strip.on_fader(1.0)
    await settle()
    assert backend.calls == [("set_stream_volume", 1, 100)]


async def test_an_auto_strip_is_idle_while_its_application_holds_it(surface: RecordingSurface, env: StripEnv) -> None:
    strip = auto(surface, env)
    strip.assign("Brave")
    strip.update(state())

    assert surface.strips[0].text == ["Brave", "idle"]


async def test_an_auto_strip_without_application_ignores_the_fader(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = auto(surface, env)
    strip.update(state())

    strip.on_fader(0.5)
    await settle()

    assert backend.calls == []


async def test_a_new_application_keeps_its_own_volume(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = auto(surface, env)
    strip.assign("Brave")
    strip.update(state(stream(1, volume=30)))
    strip.assign("Brave")  # the same application again changes nothing

    strip.assign("Spotify")
    strip.update(state(stream(2, "Spotify", "spotify", volume=90)))
    await settle()

    assert backend.calls == []
    assert surface.strips[0].text == ["Spotify", "90%"]


# -- assigning applications to auto strips ------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_playing_applications_fill_the_auto_strips_in_the_order_they_started() -> None:
    assigner = AutoAssigner(2, hold=5, ignore=())

    assigned = assigner.assign(state(stream(5, "Spotify"), stream(2, "Brave"), stream(9, "Steam")))

    assert assigned == ["Brave", "Spotify"]


def test_paused_ignored_and_claimed_applications_get_no_auto_strip() -> None:
    assigner = AutoAssigner(4, hold=5, ignore=("speech-dispatcher",))

    assigned = assigner.assign(
        state(
            stream(1, "Brave", corked=True),
            stream(2, "speech-dispatcher-espeak", "sd_espeak"),
            stream(3, "Firefox", "firefox"),
            stream(4, "Spotify", "spotify"),
            stream(5, "Spotify", "spotify"),
        ),
        claimed=(BROWSERS,),
    )

    assert assigned == ["Spotify", None, None, None]


def test_an_application_keeps_its_strip_for_the_hold_time_after_it_stopped() -> None:
    clock = Clock()
    assigner = AutoAssigner(1, hold=5, ignore=(), clock=clock)
    assigner.assign(state(stream(1, "Spotify")))

    clock.now = 4
    assert assigner.assign(state(stream(2, "Brave"))) == ["Spotify"]
    # it plays again in time: it stays
    clock.now = 8
    assert assigner.assign(state(stream(3, "Spotify"))) == ["Spotify"]
    clock.now = 9
    assert assigner.assign(state()) == ["Spotify"]
    clock.now = 14
    assert assigner.assign(state(stream(2, "Brave"))) == ["Brave"]


def test_without_auto_strips_nothing_is_assigned() -> None:
    assert AutoAssigner(0, hold=5, ignore=()).assign(state(stream(1))) == []


@pytest.mark.parametrize("behavior", [BehaviorConfig()])
async def test_the_volume_strip_base_needs_a_kind(surface: RecordingSurface, behavior: BehaviorConfig) -> None:
    from xtouch_daemon.strips.base import VolumeStrip

    strip = VolumeStrip(surface.strips[0], StripEnv(FakeBackend(), behavior), "x")
    with pytest.raises(NotImplementedError):
        strip.current(state())
    with pytest.raises(NotImplementedError):
        await strip.apply_volume(1)
    with pytest.raises(NotImplementedError):
        await strip.apply_mute(True)
    assert strip.inactive_text() == "off"
    assert not strip.recording(state())
    assert not strip.playing(state())
    assert not strip.is_default(state())


async def test_the_base_of_application_strips_needs_streams(surface: RecordingSurface, env: StripEnv) -> None:
    from xtouch_daemon.strips.apps import AppStrip

    with pytest.raises(NotImplementedError):
        AppStrip(surface.strips[0], env, "x").streams_in(state())


async def test_the_base_strip_does_nothing(surface: RecordingSurface, env: StripEnv) -> None:
    from xtouch_daemon.strips.base import StripController

    strip = StripController(surface.strips[0], env)
    strip.update(state())
    strip.on_fader(0.5)
    strip.on_touch(True)
    strip.on_button(Button.MUTE, True)
    strip.on_encoder(1)
    strip.on_encoder_press(True)
    assert strip.meter_targets(state()) == set()
    assert not strip.is_playing(CaptureTarget(None, True), state())
    assert surface.sent == []
    await asyncio.sleep(0)


async def test_the_encoder_of_an_auto_strip_without_volume_does_nothing(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = auto(surface, env)
    strip.assign("Brave")
    strip.update(state())

    strip.on_encoder(2)
    await settle()

    assert backend.calls == []


def recording(app: str, binary: str, corked: bool = False) -> Capture:
    return Capture(30, app, binary, "mic", Direction.INPUT, corked)


async def test_the_rec_led_of_a_group_shows_whether_one_of_its_applications_records(
    surface: RecordingSurface, env: StripEnv
) -> None:
    strip = AppGroupStrip(
        surface.strips[0], env, ("discord",), "VoIP", indicators={Button.REC: "recording", Button.SOLO: "playing"}
    )

    # it records without playing anything: the strip is idle, the LED is on all the same
    strip.update(AudioState(captures=(recording("WEBRTC VoiceEngine", "Discord"),)))
    assert surface.strips[0].leds[Button.REC] == Led.ON
    assert surface.strips[0].leds[Button.SOLO] == Led.OFF

    strip.update(AudioState(streams=(stream(1, "Discord", "discord"),)))
    assert surface.strips[0].leds[Button.REC] == Led.OFF
    assert surface.strips[0].leds[Button.SOLO] == Led.ON


async def test_the_rec_led_of_an_auto_strip_follows_its_application(surface: RecordingSurface, env: StripEnv) -> None:
    strip = AutoStrip(surface.strips[0], env, {}, indicators={Button.REC: "recording", Button.SOLO: "default"})
    capturing = AudioState(captures=(recording("Discord", "discord"),))

    strip.update(capturing)
    assert surface.strips[0].leds[Button.REC] == Led.OFF

    strip.assign("Discord")
    strip.update(capturing)
    assert surface.strips[0].leds[Button.REC] == Led.ON
    # applications are never the default
    assert surface.strips[0].leds[Button.SOLO] == Led.OFF
