"""
Which channels have sound right now, for the live view: the GUI animates them, so playing something shows which
channels take it, also those that no slot shows yet.
"""

from collections.abc import Iterable

from xtouch_daemon.audio.model import AudioState, Device, Direction
from xtouch_daemon.slots.inputs import device_matches
from xtouch_daemon.slots.model import ChannelConfig, Scene


def sounding(scene: Scene, audio: AudioState, talking: Iterable[str]) -> tuple[str, ...]:
    """
    The ids of the channels with sound, in the order of the file: an output something plays to, an input something
    records from, applications with a stream that is not paused, a person who talks (`talking`: the names of those
    who talk). Home Assistant and custom channels have no sound.
    """
    talks = {name.lower() for name in talking}
    return tuple(name for name, channel in scene.channels.items() if _sounds(channel, audio, talks))


def _sounds(channel: ChannelConfig, audio: AudioState, talks: set[str]) -> bool:
    match channel.type:
        case "apps":
            return any(stream.playing for stream in audio.streams_matching(channel.streams))
        case "output" | "input":
            return any(device.running for device in _devices(channel, audio, Direction(channel.type)))
        case "person":
            return any(person.lower() in talks for person in channel.people)
        case _:
            return False


def _devices(channel: ChannelConfig, audio: AudioState, direction: Direction) -> tuple[Device, ...]:
    """The devices of the channel that are there: those its patterns take, or the default one without patterns."""
    patterns = channel.devices
    if not patterns:
        default = audio.device(direction, None)
        return () if default is None else (default,)
    return tuple(
        device
        for device in audio.devices(direction)
        if any(device_matches(name, pattern) for pattern in patterns for name in (device.name, device.description))
    )
