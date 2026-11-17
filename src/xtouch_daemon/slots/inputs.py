"""
What the daemon sees at a moment (applications, the voice chat, processes, devices, Home Assistant), and the
presence of channels and pools in it.
"""

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass, replace

from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.slots.model import AUTO, ChannelConfig, Scene
from xtouch_daemon.slots.timing import Delayed


@dataclass(frozen=True)
class Observation:
    playing: tuple[str, ...] = ()
    """The applications with a playback stream (playing or paused), in the order they started; with those an `auto`
    pool still holds (`hold`) after they stopped."""
    recording: tuple[str, ...] = ()
    """The applications with a capture stream."""
    voice_chat: bool = False
    """Whether the voice chat reports that you are in a channel, also alone (you intend to talk)."""
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


def person_channel_of(scene: Scene, person: str) -> str | None:
    """The `person` channel of someone in the voice chat, None for none."""
    name = person.lower()
    return next((key for key, channel in scene.channels.items() if name in (p.lower() for p in channel.people)), None)


def people_of(scene: Scene, observation: Observation, present: frozenset[str], with_slot: set[str]) -> list[str]:
    """
    The people that share the slots of `auto`, in the order they came: who has no `person` channel by name, and the
    `person` channels with `in_auto` that are present and have no slot of their own by channel id.
    """
    members: dict[str, None] = {}
    for person in observation.people:
        channel = person_channel_of(scene, person)
        if channel is None:
            members[person] = None
        elif scene.channels[channel].in_auto and channel in present and channel not in with_slot:
            members[channel] = None
    return list(members)


def pool_present(scene: Scene, pool: str, observation: Observation, present: frozenset[str]) -> bool:
    """
    Whether a pool has members, counted before slots are assigned (so conditions never depend on the result):
    `auto` while anything plays that it may take or anyone is in the voice chat (people share its slots), a pool of
    channels while one of them is present.
    """
    if pool == AUTO:
        return bool(observation.people) or any(not excluded(scene, app) for app in observation.playing)
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


class Lingering:
    """
    Names (applications, people) that stay `after` seconds after they went, in the order they came: a person whose
    voice chat reconnects, or a notification sound, doesn't move a fader twice.
    """

    def __init__(self, after: float):
        self.after = after
        self._gone: dict[str, float | None] = {}
        """In the order they came: when each went, None while it is there."""

    def update(self, names: tuple[str, ...], now: float) -> tuple[str, ...]:
        for name in names:
            self._gone[name] = None
        for name, since in list(self._gone.items()):
            if name in names:
                continue
            since = self._gone[name] = now if since is None else since
            if now - since >= self.after:
                del self._gone[name]
        return tuple(self._gone)

    def deadline(self) -> float | None:
        return min((since + self.after for since in self._gone.values() if since is not None), default=None)


class PoolMembers:
    """
    The observation the pools see: the applications of `auto` stay its `hold` after they stopped, the people
    `absent_after` after they left the voice chat (like the channels).
    """

    def __init__(self, scene: Scene, absent_after: float):
        self._playing = Lingering(scene.pools[AUTO].hold)
        self._people = Lingering(absent_after)

    def update(self, observation: Observation, now: float) -> Observation:
        return replace(
            observation,
            playing=self._playing.update(observation.playing, now),
            people=self._people.update(observation.people, now),
        )

    def deadline(self) -> float | None:
        return min((d for d in (self._playing.deadline(), self._people.deadline()) if d is not None), default=None)
