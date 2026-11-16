"""
What the daemon sees at a moment (applications, the voice chat, processes, devices, Home Assistant), and the
presence of channels and pools in it.
"""

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass

from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.slots.model import AUTO, PEOPLE, ChannelConfig, Scene
from xtouch_daemon.slots.timing import Delayed


@dataclass(frozen=True)
class Observation:
    playing: tuple[str, ...] = ()
    """The applications with a playback stream (playing or paused), in the order they started; with those an `auto`
    pool still holds (`hold`) after they stopped."""
    recording: tuple[str, ...] = ()
    """The applications with a capture stream."""
    voice_chat: bool = False
    """Whether the voice chat reports a channel with at least one other person."""
    people: tuple[str, ...] = ()
    """The people in the voice chat, in the provider's order."""
    processes: frozenset[str] = frozenset()
    devices: frozenset[str] = frozenset()
    """The node names (and descriptions) of the outputs and inputs that are there."""
    homeassistant: frozenset[str] = frozenset()
    """The states whose input switch in Home Assistant is on."""


def app_matches(app: str, parts: Iterable[str]) -> bool:
    """Whether the name contains one of the parts, ignoring case (as `match` of `apps` strips)."""
    return any(part.lower() in app.lower() for part in parts)


def device_matches(device: str, pattern: str) -> bool:
    """By name; `*` and `?` are wildcards."""
    return fnmatch.fnmatchcase(device, pattern)


def owner_of(scene: Scene, app: str) -> str | None:
    """The first `apps` channel (in the order of the file) whose `match` takes the application."""
    return next(
        (
            name
            for name, channel in scene.channels.items()
            if channel.type == "apps" and app_matches(app, channel.streams)
        ),
        None,
    )


def excluded(scene: Scene, app: str) -> bool:
    """Whether the `auto` pool never takes it: `exclude`, or a channel with `in_auto = false` has it."""
    if app_matches(app, expand(scene.pools[AUTO].exclude, Kind.STREAMS)):
        return True
    owner = owner_of(scene, app)
    return owner is not None and not scene.channels[owner].in_auto


def present_now(channel: ChannelConfig, observation: Observation) -> bool:
    """Whether a channel has something to control in the observation (without `absent_after`)."""
    match channel.type:
        case "apps":
            return any(app_matches(app, channel.streams) for app in observation.playing)
        case "output" | "input":
            patterns = channel.devices
            return not patterns or any(
                device_matches(device, pattern) for pattern in patterns for device in observation.devices
            )
        case "person":
            names = {name.lower() for name in channel.people}
            return any(person.lower() in names for person in observation.people)
        case _:
            # homeassistant: its entities are always there
            return True


def people_without_channel(scene: Scene, observation: Observation) -> tuple[str, ...]:
    """The people in the voice chat that no `person` channel has: the members of the pool `people`."""
    names = {person.lower() for channel in scene.channels.values() for person in channel.people}
    return tuple(person for person in observation.people if person.lower() not in names)


def pool_present(scene: Scene, pool: str, observation: Observation, present: frozenset[str]) -> bool:
    """
    Whether a pool has members, counted before slots are assigned (so conditions never depend on the result):
    `auto` while anything plays that it may take, `people` while someone has no `person` channel, a pool of
    channels while one of them is present.
    """
    if pool == AUTO:
        return any(not excluded(scene, app) for app in observation.playing)
    if pool == PEOPLE:
        return bool(people_without_channel(scene, observation))
    return any(channel in present for channel in scene.members_of(scene.pools[pool].channels))


class Presence:
    """The channels that are present, each kept `absent_after` seconds after it had nothing to control any more."""

    def __init__(self, scene: Scene, absent_after: float):
        self.scene = scene
        self._delayed = {
            name: Delayed(0.0, channel.absent_after if channel.absent_after is not None else absent_after)
            for name, channel in scene.channels.items()
        }

    def update(self, observation: Observation, now: float) -> frozenset[str]:
        for name, delayed in self._delayed.items():
            delayed.update(present_now(self.scene.channels[name], observation), now)
        return frozenset(name for name, delayed in self._delayed.items() if delayed.value)

    def deadline(self) -> float | None:
        """When an absence becomes final, if one is pending."""
        return min((d for delayed in self._delayed.values() if (d := delayed.deadline()) is not None), default=None)
