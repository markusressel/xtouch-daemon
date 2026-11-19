"""
The world of a situation for a virtual twin (see docs/development/design/previews.md): the sound server and the
voice chat that a `Situation` stands for, made up, so the twin's strips go through the normal path of a step
(`Observer.observe()`).

The situation says what is there (`Situation.observation()`, the same rules as for the real device); this module makes
an `AudioState` and the people of a voice chat of it.
"""

import re
from dataclasses import dataclass

from xtouch_daemon.audio.model import AudioState, Device, Direction, Stream
from xtouch_daemon.slots.inputs import Attendee, Observation, SoundDevice
from xtouch_daemon.slots.model import Scene
from xtouch_daemon.slots.outcomes import Situation

DEFAULT_OUTPUT = "twin_output"
DEFAULT_INPUT = "twin_input"
"""The default devices of the twin, there while an `output` or `input` channel has no `devices`."""

_BINARY = re.compile(r"^(?P<app>.*) \((?P<binary>[^()]*)\)$")


@dataclass(frozen=True)
class Names:
    """
    What the real system shows right now, as plain strings: the twin takes these as stand-ins first (as the device
    does for a situation), and nothing else of reality.
    """

    apps: tuple[str, ...] = ()
    """The applications that play, as `Observation.playing` names them."""
    people: tuple[str, ...] = ()
    """The people in the voice chat."""
    devices: tuple[SoundDevice, ...] = ()
    """The outputs and inputs there are."""
    defaults: frozenset[str] = frozenset()
    """The node names of the default output and input."""

    @classmethod
    def of(cls, observation: Observation) -> Names:
        return cls(
            observation.playing,
            tuple(person.name for person in observation.people),
            observation.sound_devices,
            observation.defaults,
        )


@dataclass(frozen=True)
class World:
    """What a twin's sound server and voice chat show."""

    audio: AudioState
    people: tuple[str, ...]


def world(scene: Scene, situation: Situation, names: Names) -> World:
    """The sound server and the voice chat for `situation`, with the real `names` as stand-ins first."""
    real = Observation(
        playing=names.apps,
        voice_chat=bool(names.people),
        people=tuple(Attendee(person, person) for person in names.people),
        sound_devices=names.devices,
        defaults=names.defaults,
    )
    observation = situation.observation(scene, real)
    return World(_audio(scene, observation), tuple(person.name for person in observation.people))


def world_of_now(names: Names) -> World:
    """
    The world as it is right now, by its names: the applications, people and devices that are there (a twin of edits
    without a situation, see `Twin`). The channels find them as they find the real ones.
    """
    outputs = tuple(_device(device) for device in names.devices if device.direction == "output")
    inputs = tuple(_device(device) for device in names.devices if device.direction == "input")

    def default(devices: tuple[Device, ...]) -> str | None:
        return next((device.name for device in devices if device.name in names.defaults), None)

    audio = AudioState(
        outputs=outputs,
        inputs=inputs,
        streams=tuple(_stream(index, name) for index, name in enumerate(names.apps, start=1)),
        default_output=default(outputs),
        default_input=default(inputs),
    )
    return World(audio, names.people)


def _audio(scene: Scene, observation: Observation) -> AudioState:
    streams = tuple(_stream(index, name) for index, name in enumerate(observation.playing, start=1))
    outputs: dict[str, Device] = {}
    inputs: dict[str, Device] = {}

    def add(device: SoundDevice) -> None:
        target = outputs if device.direction == "output" else inputs
        target.setdefault(device.name, _device(device))

    for stand_in in observation.sound_devices:
        add(stand_in)
    default_output = default_input = None
    for channel in scene.channels.values():
        if channel.type not in ("output", "input"):
            continue
        direction: str = channel.type
        if not channel.devices:
            # the channel takes the default device of its direction
            name = DEFAULT_OUTPUT if direction == "output" else DEFAULT_INPUT
            add(SoundDevice(name, f"Twin {direction}", direction))  # pyright: ignore[reportArgumentType]
            if direction == "output":
                default_output = name
            else:
                default_input = name
            continue
        for pattern in channel.devices:
            if pattern in observation.devices:
                node = concrete(pattern)
                add(SoundDevice(node, node, direction))  # pyright: ignore[reportArgumentType]
    return AudioState(
        outputs=tuple(outputs.values()),
        inputs=tuple(inputs.values()),
        streams=streams,
        default_output=default_output,
        default_input=default_input,
    )


def concrete(pattern: str) -> str:
    """A node name that a device pattern takes: `bluez_output.*` is `bluez_output.1`."""
    return pattern.replace("*", "1").replace("?", "x")


def _stream(index: int, name: str) -> Stream:
    match = _BINARY.match(name)
    app, binary = (match["app"], match["binary"]) if match else (name, name)
    return Stream(index=index, app=app, binary=binary, volume=100, muted=False, corked=False)


def _device(device: SoundDevice) -> Device:
    direction = Direction.OUTPUT if device.direction == "output" else Direction.INPUT
    return Device(device.name, device.description, direction, volume=100, muted=False, running=True)
