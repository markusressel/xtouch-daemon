"""
What goes over the socket of the live view: snapshots of the device, the requests of the GUI and their replies.
"""

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import SecretStr

from xtouch_daemon.config.model import Config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import StripEvent
from xtouch_daemon.hardware.strip import glided
from xtouch_daemon.simulator.device import METER_FALL
from xtouch_daemon.slots.outcomes import Situation

VERSION = 2
"""Changes when a line means something else; a client ignores lines of another version."""


FEATURES = ("preview", "mode", "override", "play", "situation", "on_device", "test", "log")
"""The requests this daemon takes. An older daemon tells none, so the GUI knows that it can't preview."""


@dataclass(frozen=True)
class Glide:
    """A fader on its way to `target`: the GUI draws the rest of the way, as the daemon moves it (`hardware.strip`)."""

    at: float
    """When the fader was at the position of the state (`time.monotonic()`, the same in the GUI on this machine)."""
    velocity: float
    """Its speed then, in ranges (0..1) per second."""
    target: float
    """Where it goes, 0..1."""
    slow: bool
    """Whether it moves slowly (see `FADER_SLOW_SMOOTH_TIME`)."""


@dataclass(frozen=True)
class StripState:
    """
    What one strip shows. What moves by itself is told once, with its time, and the GUI draws it moving: a meter falls
    from its level (`meter_now()`), a fader glides to its target (`fader_now()`). The daemon sends a state only when it
    changed otherwise.
    """

    color: str
    """The backlight of the LCD, a color name of the configuration ("off" for dark)."""
    text: tuple[str, str]
    """The two lines of the LCD."""
    leds: dict[str, str]
    """The LED of each button ("rec", "solo", "mute", "select"): "off", "on" or "flash"."""
    ring: int
    """The position of the LED ring, 0 (off) to `protocol.RING_MAX`."""
    ring_mode: str
    """How the ring shows the position, a `RingMode` in lower case: "dot", "boost_cut", "wrap" or "spread"."""
    fader: float | None
    """Where the fader is (0..1), None while that is not known."""
    touched: bool
    """Whether a finger is on the fader."""
    meter: int
    """The level of the meter, 0..`protocol.METER_MAX`, as it was set: it falls from there (see `meter_at`)."""
    meter_at: float | None = None
    """When the meter was set (`time.monotonic()`); None for a level that stays (a demo)."""
    glide: Glide | None = None
    """How the fader glides from `fader`, None while it stays."""
    ring_center: bool = False
    """Whether the center bit of the ring is set: the two LEDs at its ends light (only the test sets it)."""


def meter_now(state: StripState, now: float) -> int:
    """The level the meter of `state` shows at `now`: it falls by a level every `METER_FALL`, as the device lets it."""
    if state.meter_at is None:
        return state.meter
    return max(0, state.meter - int(max(0.0, now - state.meter_at) / METER_FALL))


def fader_now(state: StripState, now: float) -> float | None:
    """Where the fader of `state` is at `now`: on its way to the target of its glide, as the daemon moves it."""
    glide = state.glide
    if glide is None or state.fader is None:
        return state.fader
    scale = protocol.FADER_MAX
    position = glided(
        state.fader * scale, glide.velocity * scale, glide.target * scale, glide.slow, max(0.0, now - glide.at)
    )
    return position / scale


def steady(states: tuple[StripState, ...]) -> tuple[StripState, ...]:
    """
    What `states` tell apart from where their glides are now: two that differ only in that need not be sent, as the
    GUI draws the glide.
    """
    return tuple(
        state
        if state.glide is None
        else dataclasses.replace(state, fader=None, glide=dataclasses.replace(state.glide, at=0.0, velocity=0.0))
        for state in states
    )


def moving(state: StripState, now: float) -> bool:
    """Whether something of `state` still moves by itself at `now`: its meter falls, or its fader glides."""
    if state.meter_at is not None and meter_now(state, now) > 0:
        return True
    return state.glide is not None and fader_now(state, now) != state.glide.target


@dataclass(frozen=True)
class MqttState:
    """The connection to the MQTT broker of Home Assistant."""

    broker: str
    """`host:port`."""
    username: str | None
    connected: bool
    ready: bool
    """Connected, and the states Home Assistant keeps for the entities are in."""
    error: str | None
    """Why the last attempt to connect failed or the connection ended (the broker's words), None while connected."""
    entities: int
    """The entities of the configuration in Home Assistant."""


@dataclass(frozen=True)
class VoipState:
    """Where the participants of `voip` strips come from (`[voip]`)."""

    provider: str
    """`bridge` or `demo`."""
    connected: bool
    """Whether the provider knows the voice chat now; for `bridge`: a plugin is connected."""
    client: str | None
    """What the plugin calls its voice chat client, e.g. "mumble"."""
    channel: str | None
    """The channel of the user, if the plugin tells it."""
    participants: int
    names: tuple[str, ...] = ()
    """The names of the participants, in the order of the provider."""
    ids: tuple[str, ...] = ()
    """The ids of the participants (what the provider knows them by), as `names`; empty from an older daemon."""


@dataclass(frozen=True)
class SlotView:
    """What a slot shows (see `slots.resolver.Shown`) and why."""

    slot: int
    candidate: int | None
    """The index of the candidate in the slot's stack, None for nothing at all."""
    channel: str | None
    pool: str | None
    member: str | None
    """The application (`app:<name>`), person (`person:<name>`) or channel a pool hands out."""
    why: tuple[str, ...]


@dataclass(frozen=True)
class StateView:
    """A state or mode."""

    name: str
    value: bool
    mode: bool
    """Whether it is a mode (picked with `SetMode`, not overridden)."""
    since: str | None
    """When it got its value, an ISO time; None before the first step."""
    source: str | None
    """What turned it on (`mumble runs`, `override`, ...), None while it is off."""
    override: str
    """`auto`, `on` or `off`."""


@dataclass(frozen=True)
class SlotsState:
    """The slots of a configuration of channels, states and slots."""

    mode: str
    """The mode that is on (`default` without another one)."""
    mode_pick: str | None
    """The mode picked by hand, None while the rules decide."""
    slots: tuple[SlotView, ...]
    states: tuple[StateView, ...]
    waiting: dict[str, tuple[str, ...]]
    """Per pool, the members that got no slot."""


@dataclass(frozen=True)
class Snapshot:
    """The state of the daemon and of everything the device shows."""

    config: str
    """The `fingerprint()` of the configuration the daemon uses."""
    device: bool
    """Whether the device is connected. The strips show what it would show (and does once it is back)."""
    sound_server: bool
    mqtt: bool | None
    """Whether the MQTT broker is connected; None without an [mqtt] section."""
    strips: tuple[StripState, ...]
    mqtt_state: MqttState | None = None
    """More on the connection of `mqtt` (an older daemon does not tell it)."""
    daemon_version: str | None = None
    """The version of the daemon that runs (an older daemon does not tell it)."""
    preview: bool = False
    """
    Whether the daemon runs a configuration that a GUI previews (`StartPreview`) instead of its file; `config` is the
    fingerprint of that one then.
    """
    features: tuple[str, ...] = ()
    """The requests the daemon takes (`FEATURES`), none for an older daemon."""
    voip: VoipState | None = None
    """The voice chat, None without `[voip]` (or for an older daemon)."""
    slots: SlotsState | None = None
    """The slots, states and mode; None for an older daemon."""
    virtual: bool = False
    """Whether the device is the virtual one (`run --virtual-device`), which the GUI can host."""
    simulated: bool = False
    """Whether the device shows a situation of the preview (`StartPreview.situation`): `slots` are its slots then."""
    test: bool = False
    """Whether the device runs its test (`StartTest`): the strips show the test, not the slots."""
    device_plugged: bool = False
    """
    Whether the device of `[device] name` is plugged in while the daemon drives the virtual one (`virtual`): the GUI
    offers to switch to it.
    """


@dataclass(frozen=True)
class TwinView:
    """
    What the virtual twin of a client shows (a `StartPreview` not `on_device`): its strips as its mirror of the device
    has them, and its slots, states and mode. Sent to the client of the twin only.
    """

    config: str
    """The `fingerprint()` of the configuration the twin runs."""
    strips: tuple[StripState, ...]
    slots: SlotsState


@dataclass(frozen=True)
class StartPreview:
    """
    Run this configuration (the whole TOML text, None: the file's), with a `situation` in that situation instead of
    the real one (see `docs/development/design/previews.md`), without writing the file. `on_device`: on the device,
    instead of the file. Otherwise on a virtual twin of this client: the daemon sends it a `TwinView` with every
    change, and without a `situation` the twin runs the situation of now. The daemon answers with a `Reply` of kind
    "preview"; sent again, the preview follows (also to the other place). It ends with `EndPreview`, with the
    connection and without a request for `daemon.PREVIEW_TIMEOUT` (see `KeepPreview`); on the device also when the
    file is loaded again or another client takes the device ("ended").
    """

    config: str | None
    situation: Situation | None = None
    on_device: bool = True


@dataclass(frozen=True)
class KeepPreview:
    """The heartbeat of a preview: the client is still there (a hung GUI keeps its connection open, but sends none)."""


@dataclass(frozen=True)
class EndPreview:
    """The preview of this client is not needed any more: the device runs the file again, the twin ends."""


@dataclass(frozen=True)
class SetMode:
    """With slots: pick a mode, or `auto` for the rules. The daemon answers with a `Reply` of kind "mode"."""

    mode: str


@dataclass(frozen=True)
class SetOverride:
    """
    With slots: the override of a state that is no mode, `auto`, `on` or `off`. The daemon answers with a `Reply` of
    kind "override".
    """

    state: str
    value: str


@dataclass(frozen=True)
class Play:
    """
    A hand on the device from the GUI (the mouse on the drawing in Play): the daemon takes `event` as if the device
    sent it, so the mixer acts, and a motorized fader follows once let go. No answer.
    """

    event: StripEvent
    preview: bool = False
    """The hand is on the virtual twin of this client (its preview not `on_device`), not on the device."""


@dataclass(frozen=True)
class ForgetDevice:
    """Forget a device the daemon remembers (see `KnownDevice`), e.g. headphones that are gone for good. No answer."""

    name: str
    direction: str


@dataclass(frozen=True)
class StartTest:
    """
    Run the test of the device (`hardware.selftest`): the sweep, then every strip answers its controls, on the device
    and on its drawing (`Play` is an input of the test then). The slots go on, but nothing of theirs reaches the device
    until the test ends: with `EndTest`, with the connection, without a request for `daemon.TEST_TIMEOUT` (see
    `KeepTest`), when the device goes away, or when a preview takes the device ("test_ended"). The daemon answers
    with a `Reply` of kind "test". Another client that starts it takes it over.
    """


@dataclass(frozen=True)
class KeepTest:
    """The heartbeat of the test: the client is still there."""


@dataclass(frozen=True)
class EndTest:
    """The test of this client is done: the device shows the slots again."""


@dataclass(frozen=True)
class WatchLog:
    """
    Send the log of the daemon: the records it keeps (`live.log.LOG_SIZE`) at once, in a `LogLines` with `backlog`,
    then every new one, until `EndLog` or the end of the connection. The `LiveServer` answers it, not the daemon.
    """


@dataclass(frozen=True)
class EndLog:
    """The log is not needed any more (its window was closed)."""


type DaemonRequest = (
    StartPreview
    | KeepPreview
    | EndPreview
    | SetMode
    | SetOverride
    | Play
    | ForgetDevice
    | StartTest
    | KeepTest
    | EndTest
)
"""The requests the daemon handles (`LiveServer`'s `on_request`)."""


type LogRequest = WatchLog | EndLog
"""The requests the `LiveServer` handles itself."""


type Request = DaemonRequest | LogRequest


@dataclass(frozen=True)
class KnownDevice:
    """
    A device the daemon saw (see `runtime.device_memory`): it suggests it for a configuration also while it is not
    there, e.g. Bluetooth headphones that are off, or the digital output while the card is in its analog profile.
    """

    name: str
    description: str
    direction: str
    """"output" or "input"."""
    card: str | None
    """The sound card it belongs to, None for others (Bluetooth has its own cards)."""
    profile: str | None
    """The profile the card was in when the device was there: the one that makes it."""
    seen: float
    """When it was there last, in seconds since the epoch."""


@dataclass(frozen=True)
class KnownDevices:
    """Every device the daemon remembers, sent when a client connects and whenever they change."""

    devices: tuple[KnownDevice, ...]


@dataclass(frozen=True)
class LogEntry:
    """A record of the log of the daemon, as its terminal or the journal show it."""

    seq: int
    """Counts the records of a daemon from 1: a gap means records that went by while the client fell behind."""
    time: float
    """When it was logged, in seconds since the epoch."""
    level: str
    """`DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`."""
    logger: str
    """The name of the logger, e.g. `xtouch_daemon.runtime.daemon`."""
    message: str
    """The message, with the traceback of an exception (more lines then)."""


@dataclass(frozen=True)
class LogLines:
    """Records of the log, for the clients that watch it (`WatchLog`)."""

    entries: tuple[LogEntry, ...]
    backlog: bool = False
    """The records the daemon kept, the answer to `WatchLog`: the client starts over with them."""


type ReplyKind = Literal["preview", "ended", "mode", "override", "test", "test_ended", "error"]


@dataclass(frozen=True)
class Reply:
    """
    An answer of the daemon, or news for a client. "preview": whether a `StartPreview` runs now (`message` says why
    not, e.g. the errors of the configuration, as `check-config` tells them). "ended": the preview of this client
    ended, `message` says why. "mode" and "override": whether a `SetMode` (`message` is the mode then,
    or why not) or a `SetOverride` was carried out. "test": whether a `StartTest` runs now (`message` says why not).
    "test_ended": the test of this client ended, `message` says why. "error": a request could not be read, or is not
    allowed.
    """

    kind: ReplyKind
    ok: bool
    message: str = ""


def fingerprint(config: Config) -> str:
    """
    A short hash of everything in a configuration, so the GUI can tell whether the daemon uses the saved file (a
    reload keeps the old configuration when the new one can't be used).
    """

    def plain(value: Any) -> Any:
        return value.get_secret_value() if isinstance(value, SecretStr) else str(value)

    # a configuration not read from a file (`Config()`) has no slots
    slots = config._slots.data if config._slots is not None else None
    data = json.dumps([config.model_dump(), slots], default=plain, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]
