"""
What the daemon sees at a moment (applications, the voice chat, processes, devices, Home Assistant), and the
presence of channels and pools in it.
"""

import fnmatch
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.slots.model import APPS, AUTO, PEOPLE, ChannelConfig, Scene
from xtouch_daemon.slots.timing import Delayed


@dataclass(frozen=True)
class Attendee:
    """Someone in the voice chat: `id` is what the provider knows them by while they are there."""

    id: str
    name: str


@dataclass(frozen=True)
class App:
    """An application of `apps` and `auto`, by its name (see `stream_name()`)."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Channel:
    """A channel as a member of a pool (or of `apps` and `auto`, an `apps` channel without a slot as a whole)."""

    id: str

    def __str__(self) -> str:
        return self.id


@dataclass(frozen=True)
class Person:
    """
    A member of `people` and `auto`: who is in the voice chat (`id`, `name`), with the `person` channel they have
    (`channel`), if any.
    """

    id: str
    name: str
    channel: str | None = None

    def __str__(self) -> str:
        return self.channel or self.name


type Member = App | Channel | Person
"""What a pool hands out: never told apart by name (someone called `browser` is no channel)."""


def channel_of(member: Member | None) -> str | None:
    """The channel a member is, or has (a person with a `person` channel)."""
    match member:
        case Channel(id=channel) | Person(channel=channel):
            return channel
        case _:
            return None


@dataclass(frozen=True)
class Observation:
    playing: tuple[str, ...] = ()
    """The applications with a playback stream (playing or paused), in the order they started; with those `apps`
    still holds (`hold`) after they stopped."""
    recording: tuple[str, ...] = ()
    """The applications with a capture stream."""
    voice_chat: bool = False
    """Whether the voice chat reports that you are in a channel, also alone (you intend to talk)."""
    people: tuple[Attendee, ...] = ()
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
    """Whether `apps` and `auto` never take it: `[pool.apps] exclude`, or a channel with `in_pool = false` has it."""
    if app_matches(app, expand(scene.apps.exclude, Kind.STREAMS)):
        return True
    owner = owner_of(scene, app)
    return owner is not None and not scene.channels[owner].in_pool


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
            return any(person.name.lower() in names for person in observation.people)
        case _:
            # homeassistant: its entities are always there
            return True


def person_channel_of(scene: Scene, person: str) -> str | None:
    """The `person` channel of someone in the voice chat, None for none."""
    name = person.lower()
    return next((key for key, channel in scene.channels.items() if name in (p.lower() for p in channel.people)), None)


def people_of(scene: Scene, observation: Observation, present: frozenset[str], with_slot: set[str]) -> list[Person]:
    """
    The members of `people` (and of `auto`), in the order they came: who has no `person` channel, and the `person`
    channels with `in_pool` that are present and have no slot of their own (once, for the first of its names in the
    voice chat).
    """
    members: list[Person] = []
    for attendee in observation.people:
        channel = person_channel_of(scene, attendee.name)
        if channel is None:
            members.append(Person(attendee.id, attendee.name))
        elif (
            scene.channels[channel].in_pool
            and channel in present
            and channel not in with_slot
            and all(person.channel != channel for person in members)
        ):
            members.append(Person(attendee.id, attendee.name, channel))
    return members


def pool_present(scene: Scene, pool: str, observation: Observation, present: frozenset[str]) -> bool:
    """
    Whether a pool has members, counted before slots are assigned (so conditions never depend on the result): `apps`
    while anything plays that it may take, `people` while anyone is in the voice chat who would be one of them (also
    someone whose `person` channel has a slot of its own), `auto` while either is, a pool of channels while one of
    them is present.
    """
    if pool == APPS:
        return any(not excluded(scene, app) for app in observation.playing)
    if pool == PEOPLE:
        people = (person_channel_of(scene, attendee.name) for attendee in observation.people)
        return any(channel is None or scene.channels[channel].in_pool for channel in people)
    if pool == AUTO:
        return pool_present(scene, APPS, observation, present) or pool_present(scene, PEOPLE, observation, present)
    return any(channel in present for channel in scene.channels_of(pool))


class Presence:
    """The channels that are present, each kept `absent_after` seconds after it had nothing to control any more."""

    def __init__(self, scene: Scene, absent_after: float):
        self.scene = scene
        self._delayed = {
            name: Delayed(0.0, channel.absent_after if channel.absent_after is not None else absent_after)
            for name, channel in scene.channels.items()
        }

    def carry(self, before: Presence) -> None:
        """Goes on from where `before` was (a reload): the channels with the same id."""
        for name, delayed in self._delayed.items():
            if name in before._delayed:
                delayed.carry(before._delayed[name])

    def update(self, observation: Observation, now: float) -> frozenset[str]:
        for name, delayed in self._delayed.items():
            delayed.update(present_now(self.scene.channels[name], observation), now)
        return frozenset(name for name, delayed in self._delayed.items() if delayed.value)

    def deadline(self) -> float | None:
        """When an absence becomes final, if one is pending."""
        return min((d for delayed in self._delayed.values() if (d := delayed.deadline()) is not None), default=None)


class Lingering[T]:
    """
    Applications or people that stay `after` seconds after they went, in the order they came: a person whose voice
    chat reconnects, or a notification sound, doesn't move a fader twice.
    """

    def __init__(self, after: float, successor: Callable[[T, T], bool] = lambda gone, new: False):
        """`successor(gone, new)`: whether `new` takes the place of `gone` (someone who reconnected, by name)."""
        self.after = after
        self.successor = successor
        self._gone: dict[T, float | None] = {}
        """In the order they came: when each went, None while it is there."""

    def update(self, names: tuple[T, ...], now: float) -> tuple[T, ...]:
        for name in names:
            if name not in self._gone:
                gone = next(
                    (g for g, since in self._gone.items() if since is not None and self.successor(g, name)), None
                )
                if gone is not None:
                    self._gone = {name if key == gone else key: since for key, since in self._gone.items()}
            self._gone[name] = None
        for name, since in list(self._gone.items()):
            if name in names:
                continue
            since = self._gone[name] = now if since is None else since
            if now - since >= self.after:
                del self._gone[name]
        return tuple(self._gone)

    def carry(self, before: Lingering[T]) -> None:
        """Goes on from where `before` was (a reload), with its own time after."""
        self._gone = dict(before._gone)

    def deadline(self) -> float | None:
        return min((since + self.after for since in self._gone.values() if since is not None), default=None)


class PoolMembers:
    """
    The observation the pools see: the applications stay `[pool.apps] hold` after they stopped, the people
    `absent_after` after they left the voice chat (like the channels).
    """

    def __init__(self, scene: Scene, absent_after: float):
        self._playing = Lingering[str](scene.apps.hold)
        # a reconnect gets a new id: the same name takes the place of who left
        self._people = Lingering[Attendee](absent_after, lambda gone, new: gone.name == new.name)

    def carry(self, before: PoolMembers) -> None:
        """Goes on from where `before` was (a reload)."""
        self._playing.carry(before._playing)
        self._people.carry(before._people)

    def update(self, observation: Observation, now: float) -> Observation:
        return replace(
            observation,
            playing=self._playing.update(observation.playing, now),
            people=self._people.update(observation.people, now),
        )

    def deadline(self) -> float | None:
        return min((d for d in (self._playing.deadline(), self._people.deadline()) if d is not None), default=None)
