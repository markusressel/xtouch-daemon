"""
A snapshot of the audio system, as far as the strips need it: the output and input devices, the playback and
recording streams of applications, and the defaults. Immutable, so every strip sees the same consistent state.
"""

import fnmatch
from dataclasses import dataclass, field
from enum import StrEnum


class Direction(StrEnum):
    OUTPUT = "output"
    INPUT = "input"


@dataclass(frozen=True)
class Device:
    """An output (a sink) or an input (a source) of the sound server."""

    name: str
    """The node name, e.g. `alsa_output.pci-0000_11_00.4.analog-stereo`: stable across restarts."""
    description: str
    direction: Direction
    volume: int
    """Percent, the loudest channel."""
    muted: bool
    running: bool
    """Whether audio flows: something plays to the output or records from the input."""
    card: str | None = None
    """The name of the sound card it belongs to (its profile decides which devices it has), None for others."""
    balance: float | None = None
    """-1 (only left) .. 0 (centered) .. 1 (only right); None without left and right channels (mono)."""

    def matches(self, name: str) -> bool:
        """By node name or description; `*` and `?` are wildcards (e.g. `bluez_output.*`, every Bluetooth output)."""
        if "*" in name or "?" in name:
            return fnmatch.fnmatchcase(self.name, name) or fnmatch.fnmatchcase(self.description, name)
        return name in (self.name, self.description)


@dataclass(frozen=True)
class Profile:
    """A profile of a sound card: which outputs and inputs it has, e.g. analog or digital (S/PDIF) output."""

    name: str
    """E.g. `output:iec958-stereo+input:analog-stereo`."""
    description: str
    """E.g. `Digital Stereo (IEC958) Output + Analog Stereo Input`."""

    def matches(self, name: str) -> bool:
        return name in (self.name, self.description)


@dataclass(frozen=True)
class Card:
    """A sound card: one of its profiles is active."""

    name: str
    """E.g. `alsa_card.pci-0000_11_00.4`."""
    profile: str
    """The name of the active profile."""
    profiles: tuple[Profile, ...] = ()
    description: str = ""
    """E.g. `Family 17h/19h HD Audio Controller`."""

    def matches(self, name: str) -> bool:
        """By name or description; `*` and `?` are wildcards (like `Device.matches`)."""
        names = (self.name, self.description) if self.description else (self.name,)
        if "*" in name or "?" in name:
            return any(fnmatch.fnmatchcase(value, name) for value in names)
        return name in names

    def profile_named(self, name: str) -> Profile | None:
        """A profile by its name or description."""
        return next((profile for profile in self.profiles if profile.matches(name)), None)


@dataclass(frozen=True)
class Stream:
    """A playback stream of an application (a PulseAudio "sink input")."""

    index: int
    app: str
    """The name of the application (`application.name`), or its binary."""
    binary: str
    volume: int
    """Percent, the loudest channel."""
    muted: bool
    corked: bool
    """Paused by the application: no audio flows."""
    balance: float | None = None
    """-1 (only left) .. 0 (centered) .. 1 (only right); None without left and right channels (mono)."""
    pid: int | None = None
    """The process that plays it (`application.process.id`)."""

    @property
    def playing(self) -> bool:
        return not self.corked

    def matches(self, patterns: tuple[str, ...]) -> bool:
        """Whether the application name or binary contains one of the patterns (ignoring case)."""
        return _app_matches(self.app, self.binary, patterns)


@dataclass(frozen=True)
class Capture:
    """
    A recording stream of an application (a PulseAudio "source output"). Passive ones, which only show a level
    (the meters of this daemon, pavucontrol's), are not captures here: they don't use the device.
    """

    index: int
    app: str
    binary: str
    device: str | None
    """The node name of the input it records, or of the output whose monitor it records; None for anything else."""
    direction: Direction | None
    corked: bool

    @property
    def recording(self) -> bool:
        return not self.corked

    def matches(self, patterns: tuple[str, ...]) -> bool:
        """Whether the application name or binary contains one of the patterns (ignoring case)."""
        return _app_matches(self.app, self.binary, patterns)


def _app_matches(app: str, binary: str, patterns: tuple[str, ...]) -> bool:
    values = [value.lower() for value in (app, binary) if value]
    return any(pattern.lower() in value for pattern in patterns for value in values)


@dataclass(frozen=True)
class AudioState:
    outputs: tuple[Device, ...] = ()
    inputs: tuple[Device, ...] = ()
    streams: tuple[Stream, ...] = ()
    captures: tuple[Capture, ...] = ()
    cards: tuple[Card, ...] = ()
    default_output: str | None = None
    default_input: str | None = None
    connected: bool = field(default=True)
    """False while the sound server is not reachable: everything else is empty then."""

    def devices(self, direction: Direction) -> tuple[Device, ...]:
        return self.outputs if direction == Direction.OUTPUT else self.inputs

    def default_name(self, direction: Direction) -> str | None:
        return self.default_output if direction == Direction.OUTPUT else self.default_input

    def device(self, direction: Direction, name: str | None) -> Device | None:
        """A device by its node name or description, or the default device for None."""
        if name is None:
            name = self.default_name(direction)
            if name is None:
                return None
        return next((device for device in self.devices(direction) if device.matches(name)), None)

    def devices_matching(self, direction: Direction, names: tuple[str, ...]) -> tuple[Device, ...]:
        """The devices of `names` that are there, in their order (see `Device.matches`)."""
        found: dict[str, Device] = {}
        for name in names:
            found.update((device.name, device) for device in self.devices(direction) if device.matches(name))
        return tuple(found.values())

    def card(self, name: str | None) -> Card | None:
        return next((card for card in self.cards if card.name == name), None)

    def card_matching(self, pattern: str) -> Card | None:
        """The first card of the name or description (see `Card.matches`)."""
        return next((card for card in self.cards if card.matches(pattern)), None)

    def is_default(self, device: Device) -> bool:
        return self.default_name(device.direction) == device.name

    def streams_matching(self, patterns: tuple[str, ...]) -> tuple[Stream, ...]:
        return tuple(stream for stream in self.streams if stream.matches(patterns))

    def streams_of_app(self, app: str) -> tuple[Stream, ...]:
        return tuple(stream for stream in self.streams if stream.app == app)

    def is_recorded(self, device: Device) -> bool:
        """Whether an application records the device (an input, or the monitor of an output) right now."""
        return any(
            capture.recording and capture.device == device.name and capture.direction == device.direction
            for capture in self.captures
        )

    def records_matching(self, patterns: tuple[str, ...]) -> bool:
        """Whether one of the applications matching `patterns` records something right now."""
        return any(capture.recording and capture.matches(patterns) for capture in self.captures)

    def records_app(self, app: str) -> bool:
        return any(capture.recording and capture.app == app for capture in self.captures)


DISCONNECTED = AudioState(connected=False)
