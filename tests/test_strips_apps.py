import asyncio
from dataclasses import replace

import pytest

from tests.conftest import FakeBackend, FakeLauncher, RecordingSurface, settle, stream
from xtouch_daemon import protocol
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Capture, Direction
from xtouch_daemon.config import AppsStripConfig, AutoStripConfig, BehaviorConfig
from xtouch_daemon.protocol import Button, Color, Led, RingMode
from xtouch_daemon.strips import build_strip
from xtouch_daemon.strips.apps import AppGroupStrip, AutoAssigner, AutoSlot, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv

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


async def test_a_group_lit_when_idle_keeps_its_backlight(surface: RecordingSurface, env: StripEnv) -> None:
    config = AppsStripConfig(type="apps", match=BROWSERS, label="Browser", color="yellow", lit_when_idle=True)
    strip = build_strip(config, surface.strips[0], env, {})
    strip.update(state(stream(1, "Spotify", "spotify")))
    await surface.settled()

    s = surface.strips[0]
    assert s.color == Color.YELLOW
    assert s.text == ["Browser", "idle"]
    # nothing to control: the fader stays down
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


async def test_an_application_that_ends_puts_the_fader_away_and_back_when_it_returns(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    strip = group(surface, env)
    strip.update(state(stream(1, volume=70)))
    await surface.settled()

    strip.update(state())
    await surface.settled()
    s = surface.strips[0]
    assert s.text == ["Browser", "idle"]
    assert surface.faders(0)[-1] == 0
    assert s.ring == (0, RingMode.DOT)

    # while idle the fader does nothing; the next stream gets the volume the group had
    strip.on_fader(0.25)
    strip.on_encoder(3)
    await settle()
    assert backend.calls == []
    strip.update(state(stream(7, volume=100)))
    await surface.settled()
    assert backend.calls == [("set_stream_volume", 7, 70)]
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


def test_a_slot_picks_among_the_applications_without_a_strip_of_their_own() -> None:
    assigner = AutoAssigner(2, hold=5, ignore=("speech",))
    playing = state(
        stream(1, "Spotify", "spotify"),
        stream(2, "Brave", "brave"),
        stream(3, "mpv", "mpv", corked=True),
        stream(4, "speech", "sd"),
        stream(5, "Steam", "steam"),
    )
    assert assigner.assign(playing, claimed=(BROWSERS,)) == ["Spotify", "Steam"]
    # paused ones too
    assert assigner.candidates(playing, claimed=(BROWSERS,)) == ["Spotify", "mpv", "Steam"]

    assigner.pick(0, 1, playing, claimed=(BROWSERS,))
    assert assigner.assigned == ["mpv", "Steam"]
    # one another slot has: they swap
    assigner.pick(0, 1, playing, claimed=(BROWSERS,))
    assert assigner.assigned == ["Steam", "mpv"]
    # around
    assigner.pick(1, 2, playing, claimed=(BROWSERS,))
    assert assigner.assigned == ["Steam", "Spotify"]
    # nothing to pick
    assigner.pick(1, 1, state(), claimed=(BROWSERS,))
    assert assigner.assigned == ["Steam", "Spotify"]


def test_an_empty_slot_picks_the_first_or_the_last() -> None:
    assigner = AutoAssigner(2, hold=5, ignore=())
    playing = state(stream(1, "Spotify", corked=True), stream(2, "mpv", corked=True))
    assigner.pick(0, 1, playing)
    assigner.pick(1, -1, playing)
    assert assigner.assigned == ["Spotify", "mpv"]


def test_a_pinned_slot_keeps_its_application() -> None:
    clock = Clock()
    assigner = AutoAssigner(1, hold=5, ignore=(), clock=clock)
    # an empty slot can't be pinned
    assigner.toggle_pin(0)
    assert assigner.pinned == set()
    assigner.assign(state(stream(1, "Spotify")))
    assigner.toggle_pin(0)

    clock.now = 100
    assert assigner.assign(state(stream(2, "Brave"))) == ["Spotify"]
    assigner.toggle_pin(0)
    assert assigner.assign(state(stream(2, "Brave"))) == ["Spotify"]
    clock.now = 106
    assert assigner.assign(state(stream(2, "Brave"))) == ["Brave"]


async def test_the_pick_knob_waits_for_its_slot(surface: RecordingSurface, env: StripEnv) -> None:
    strip = AutoStrip(surface.strips[0], env, {}, encoder="pick")
    strip.update(state())
    strip.on_encoder(1)
    strip.on_encoder_press(True)
    assert surface.strips[0].ring == (0, RingMode.DOT)


async def test_a_single_application_is_at_the_start_of_the_ring(surface: RecordingSurface, env: StripEnv) -> None:
    strip = AutoStrip(surface.strips[0], env, {}, encoder="pick")
    assigner = AutoAssigner(1, hold=5, ignore=())
    playing = state(stream(1, "Spotify"))
    strip.slot = AutoSlot(assigner, 0, lambda: playing, (), lambda: strip.assign(assigner.assign(playing)[0]))
    strip.slot.pick(1)
    strip.update(playing)
    assert surface.strips[0].ring == (1, RingMode.DOT)


async def test_the_pick_knob_says_which_one_and_whether_pinned(surface: RecordingSurface, env: StripEnv) -> None:
    strip = AutoStrip(surface.strips[0], env, {}, encoder="pick")
    assigner = AutoAssigner(1, hold=5, ignore=())
    playing = state(stream(1, "Spotify"), stream(2, "Discord"))
    strip.slot = AutoSlot(assigner, 0, lambda: playing, (), lambda: strip.update(playing))
    strip.update(playing)
    text = surface.strips[0].text

    strip.on_encoder(1)
    assert text[1] == "1/2"
    strip.on_encoder(1)
    assert text[1] == "2/2"
    strip.on_encoder_press(True)
    assert text[1] == "pinned"
    strip.on_encoder_press(True)
    assert text[1] == "auto"

    # nothing to pick: nothing to say
    strip.slot = AutoSlot(assigner, 0, lambda: state(), (), lambda: None)
    strip._end_notice()
    strip.on_encoder(1)
    assert strip.notice is None
    strip.close()


def test_without_auto_strips_nothing_is_assigned() -> None:
    assert AutoAssigner(0, hold=5, ignore=()).assign(state(stream(1))) == []


@pytest.mark.parametrize("behavior", [BehaviorConfig(max_volume=100)])
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


# -- launch -------------------------------------------------------------------------------------------------------

MUMBLE = ("mumble", "mumble://markus@voice.example.org/Gaming")
VOIP = AppsStripConfig(type="apps", match=("discord", "mumble"), label="VoIP", launch=MUMBLE)


def launching_env(env: StripEnv, *processes: str) -> tuple[StripEnv, FakeLauncher]:
    launcher = FakeLauncher()
    return replace(env, launcher=launcher, processes=lambda: frozenset(processes)), launcher


def press_select(strip: StripController) -> None:
    strip.on_button(Button.SELECT, True)
    strip.on_button(Button.SELECT, False)


async def test_select_launches_the_application_of_a_group(surface: RecordingSurface, env: StripEnv) -> None:
    env, launcher = launching_env(env, "bash", "systemd")
    strip = build_strip(VOIP, surface.strips[0], env, {})
    strip.update(state(stream(1, "Spotify", "spotify")))
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF

    press_select(strip)
    press_select(strip)

    # once: the second press comes while it starts
    (command,) = launcher.spawned
    assert command[-3:] == ["--", *MUMBLE]
    assert surface.strips[0].leds[Button.SELECT] == Led.FLASH
    strip.update(state(stream(2, "Mumble", "mumble")))
    assert surface.strips[0].leds[Button.SELECT] == Led.ON


async def test_a_group_whose_process_runs_does_not_launch(surface: RecordingSurface, env: StripEnv) -> None:
    # a silent Mumble has no stream, its process runs
    env, launcher = launching_env(env, "mumble")
    strip = build_strip(VOIP, surface.strips[0], env, {})
    strip.update(state())

    press_select(strip)

    assert launcher.spawned == []
    assert surface.strips[0].leds[Button.SELECT] == Led.ON


async def test_the_program_of_launch_counts_as_running(surface: RecordingSurface, env: StripEnv) -> None:
    env, launcher = launching_env(env, "ts3client")
    config = AppsStripConfig(type="apps", match=("teamspeak",), label="VoIP", launch=("ts3client",))
    strip = build_strip(config, surface.strips[0], env, {})
    strip.update(state())

    press_select(strip)

    assert launcher.spawned == []


async def test_launch_when_running_launches_also_while_it_runs(surface: RecordingSurface, env: StripEnv) -> None:
    env, launcher = launching_env(env, "mumble")
    config = VOIP.model_copy(update={"launch_when_running": True})
    strip = build_strip(config, surface.strips[0], env, {})
    strip.update(state())

    press_select(strip)

    assert len(launcher.spawned) == 1
    assert surface.strips[0].leds[Button.SELECT] == Led.ON


async def test_without_launch_select_does_nothing(surface: RecordingSurface, env: StripEnv) -> None:
    env, launcher = launching_env(env)
    strip = build_strip(VOIP.model_copy(update={"launch": None}), surface.strips[0], env, {})
    strip.update(state())

    press_select(strip)

    assert launcher.spawned == []
    assert not strip.launches
    assert surface.strips[0].leds[Button.SELECT] == Led.OFF


async def test_with_launch_the_other_buttons_work_as_before(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend
) -> None:
    env, launcher = launching_env(env)
    strip = build_strip(VOIP, surface.strips[0], env, {})
    assert strip.launches
    # before the first state, Select has nothing to go by
    press_select(strip)
    strip.update(state(stream(1, "Discord", "discord")))

    strip.on_button(Button.MUTE, True)
    await settle()

    assert launcher.spawned == []
    assert backend.calls == [("set_stream_mute", 1, True)]


async def test_select_launches_on_an_auto_strip_without_application(surface: RecordingSurface, env: StripEnv) -> None:
    env, launcher = launching_env(env)
    config = AutoStripConfig(type="auto", launch=("spotify",))
    strip = build_strip(config, surface.strips[0], env, {})
    assert isinstance(strip, AutoStrip)
    strip.assign("Brave")
    strip.update(state(stream(1, "Brave")))

    press_select(strip)
    assert launcher.spawned == []
    assert surface.strips[0].leds[Button.SELECT] == Led.ON

    strip.assign(None)
    strip.update(state())
    press_select(strip)
    assert len(launcher.spawned) == 1
    assert surface.strips[0].leds[Button.SELECT] == Led.FLASH


def test_a_strip_without_streams_or_application_is_absent(surface: RecordingSurface, env: StripEnv) -> None:
    browsers = group(surface, env)
    assert browsers.absent(state())
    # a paused one counts
    assert not browsers.absent(state(stream(1, "Brave", corked=True)))
    assert browsers.title == "Browser"
    strip = auto(surface, env)
    assert strip.absent(state())
    assert strip.title == "auto"
    strip.assign("WEBRTC VoiceEngine")
    assert not strip.absent(state())
    assert strip.title == "Discord"


async def test_the_processes_of_the_presets_of_a_group_count_as_running(
    surface: RecordingSurface, env: StripEnv
) -> None:
    # a game from Steam that makes no sound: Steam's reaper runs, the `.exe` of the streams is no process name
    config = AppsStripConfig(type="apps", match=("@steam-games",), label="Game", launch=("steam",))
    running, launcher = launching_env(env, "reaper")
    strip = build_strip(config, surface.strips[0], running, {})
    strip.update(state())
    press_select(strip)
    assert launcher.spawned == []

    idle, launcher = launching_env(env, "explorer.exe", "steamwebhelper")
    strip = build_strip(config, surface.strips[1], idle, {})
    strip.update(state())
    press_select(strip)
    assert len(launcher.spawned) == 1
