"""
What goes over the socket of the live view: snapshots of the device, the requests of the GUI and their replies.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import SecretStr

from xtouch_daemon.config.model import Config

VERSION = 1
"""Changes when a line means something else; a client ignores lines of another version."""


FEATURES = ("preview", "layout", "mode", "override")
"""The requests this daemon takes. An older daemon tells none, so the GUI knows that it can't preview."""


@dataclass(frozen=True)
class StripState:
    """What one strip shows."""

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
    """The level of the meter, 0..`protocol.METER_MAX`."""


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
    strips: tuple[str | None, ...] = ()
    """
    For each strip of the layout shown (an index of `Config.all_strips(layout)`, as `Snapshot.placement`), the name
    of the participant it shows: None for nobody and for the strips that are no `voip` strips.
    """
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
    layout: str | None = None
    """The name of the layout the device shows (an older daemon does not tell it)."""
    layouts: tuple[str, ...] = ()
    """The names of every layout of the configuration, the default one first."""
    voip: VoipState | None = None
    """The voice chat, None without `[voip]` (or for an older daemon)."""
    placement: tuple[int | None, ...] | None = None
    """
    For each strip of the device, the strip of the layout it shows (an index of `Config.all_strips(layout)`), None
    for a dark one; None for an older daemon, whose strips are where they are
    configured. It differs from 0..7 with `collapse` (see `placement.py`).
    """
    slots: SlotsState | None = None
    """The slots, states and mode of a configuration of channels, states and slots; None for one of layouts."""


@dataclass(frozen=True)
class StartPreview:
    """
    Run this configuration (the whole TOML text) instead of the file, without writing the file. The daemon answers
    with a `Reply` of kind "preview"; sent again, the device follows. The preview ends with `EndPreview`, with the
    connection, without a request for `daemon.PREVIEW_TIMEOUT` (see `KeepPreview`), and when the file is loaded again.
    """

    config: str


@dataclass(frozen=True)
class KeepPreview:
    """The heartbeat of a preview: the client is still there (a hung GUI keeps its connection open, but sends none)."""


@dataclass(frozen=True)
class EndPreview:
    """Back to the configuration file."""


@dataclass(frozen=True)
class SwitchLayout:
    """
    Show another layout: `layout` is its name, or "+1" ("-1") for the next (previous) one. The daemon answers with a
    `Reply` of kind "layout".
    """

    layout: str


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


type Request = StartPreview | KeepPreview | EndPreview | SwitchLayout | SetMode | SetOverride

type ReplyKind = Literal["preview", "ended", "layout", "mode", "override", "error"]


@dataclass(frozen=True)
class Reply:
    """
    An answer of the daemon, or news for a client. "preview": whether a `StartPreview` runs now (`message` says why
    not, e.g. the errors of the configuration, as `check-config` tells them). "ended": the preview of this client
    ended, `message` says why. "layout": whether a `SwitchLayout` was carried out (`message` is the layout shown
    then, or why not); "mode" and "override" the same for `SetMode` and `SetOverride`. "error": a request could not
    be read, or is not allowed.
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

    slots = config.slots.data if config.slots is not None else None
    data = json.dumps([config.model_dump(), slots], default=plain, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]
