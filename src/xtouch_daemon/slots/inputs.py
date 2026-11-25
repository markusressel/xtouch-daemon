"""
What the daemon sees at a moment (applications, the voice chat, processes, devices, Home Assistant), and the
presence of channels and pools in it.
"""

import fnmatch
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.slots.model import (
    APPS,
    AUTO,
    DEVICES,
    PEOPLE,
    AppsPoolConfig,
    ChannelConfig,
    PeoplePoolConfig,
    Scene,
)
from xtouch_daemon.slots.timing import Delayed


@dataclass(frozen=True)
class Attendee:
    """Someone in the voice chat: `id` is what the provider knows them by while they are there."""

    id: str
    name: str


@dataclass(frozen=True)
class SoundDevice:
    """An output or an input of the sound server."""

    name: str
    """The node name, e.g. `bluez_output.AA_BB_CC_DD_EE_FF.1`."""
    description: str
    direction: Literal["output", "input"]


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


@dataclass(frozen=True)
class Device:
    """A member of `devices`: an output or an input of the sound server without a channel, by its node name."""

    name: str
    direction: Literal["output", "input"]
    description: str = ""

    def __str__(self) -> str:
        return self.description or self.name


type Member = App | Channel | Person | Device
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
    pool_playing: Mapping[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    """Per pool of applications of your own, the applications it takes that play, with those it still holds."""
    recording: tuple[str, ...] = ()
    """The applications with a capture stream."""
    voice_chat: bool = False
    """Whether the voice chat reports that you are in a channel, also alone (you intend to talk)."""
    people: tuple[Attendee, ...] = ()
    """The people in the voice chat, in the provider's order."""
    processes: frozenset[str] = frozenset()
    devices: frozenset[str] = frozenset()
    """The node names (and descriptions) of the outputs and inputs that are there."""
    sound_devices: tuple[SoundDevice, ...] = ()
    """The outputs and inputs that are there, in the order the sound server lists them; with those `devices` still
    holds (`hold`) after they went."""
    defaults: frozenset[str] = frozenset()
    """The node names of the default output and the default input."""
    homeassistant: frozenset[str] = frozenset()
    """The states whose input switch in Home Assistant is on."""
    commands: frozenset[str] = frozenset()
    """The states whose `command` says on."""
    absent: frozenset[str] = frozenset()
    """The custom channels whose `present` program says they are not there; the others are."""


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


def pool_of_app(scene: Scene, app: str) -> str | None:
    """The first pool of applications of your own, in the order of the file, that a slot names and that takes it."""
    for name in scene.apps_pools:
        pool = scene.pools[name]
        assert isinstance(pool, AppsPoolConfig)
        if (
            name in scene.named
            and app_matches(app, expand(pool.match, Kind.STREAMS))
            and not app_matches(app, expand(pool.exclude, Kind.STREAMS))
        ):
            return name
    return None


def pool_of_person(scene: Scene, person: str) -> str | None:
    """The first pool of people of your own, in the order of the file, that a slot names and lists the person."""
    for name in scene.people_pools:
        pool = scene.pools[name]
        assert isinstance(pool, PeoplePoolConfig)
        if name in scene.named and person.lower() in (listed.lower() for listed in pool.people):
            return name
    return None


def excluded(scene: Scene, app: str) -> bool:
    """
    Whether `apps` and `auto` never take it: `[pool.apps] exclude`, a pool of applications of your own takes it, or a
    channel with `in_pool = false` has it.
    """
    if app_matches(app, expand(scene.apps.exclude, Kind.STREAMS)) or pool_of_app(scene, app) is not None:
        return True
    owner = owner_of(scene, app)
    return owner is not None and not scene.channels[owner].in_pool


def present_now(name: str, channel: ChannelConfig, observation: Observation) -> bool:
    """Whether a channel (`name` is its id) has something to control in the observation (without `absent_after`)."""
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
        case "custom":
            return name not in observation.absent
        case _:
            # homeassistant: its entities are always there
            return True


def device_owner(scene: Scene, device: SoundDevice, defaults: frozenset[str]) -> str | None:
    """
    The `output` or `input` channel that has a device: one whose `device` (or `choices`) takes its node name or
    description, or one without, which has the default device of its direction. None for a member of `devices`.
    """
    for name, channel in scene.channels.items():
        if channel.type != device.direction:
            continue
        patterns = channel.devices
        if (not patterns and device.name in defaults) or any(
            device_matches(value, pattern) for pattern in patterns for value in (device.name, device.description)
        ):
            return name
    return None


def devices_of(scene: Scene, observation: Observation) -> list[Device]:
    """The members of `devices`, in the order the sound server lists them: no channel has them, none is excluded."""
    exclude = scene.devices.exclude
    return [
        Device(device.name, device.direction, device.description)
        for device in observation.sound_devices
        if device_owner(scene, device, observation.defaults) is None
        and not any(
            device_matches(value, pattern) for pattern in exclude for value in (device.name, device.description)
        )
    ]


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
        if pool_of_person(scene, attendee.name) is not None:
            continue
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


def pool_people(scene: Scene, pool: str, observation: Observation, with_slot: set[str]) -> list[Person]:
    """The members of a pool of people of your own, in the order of its list: who is in the voice chat."""
    config = scene.pools[pool]
    assert isinstance(config, PeoplePoolConfig)
    by_name = {attendee.name.lower(): attendee for attendee in observation.people}
    members: list[Person] = []
    for name in config.people:
        attendee = by_name.get(name.lower())
        if attendee is None or pool_of_person(scene, attendee.name) != pool:
            continue
        channel = person_channel_of(scene, attendee.name)
        if channel is not None and channel in with_slot:
            continue
        members.append(Person(attendee.id, attendee.name, channel))
    return members


def held_by_pool(scene: Scene, app: str, present: frozenset[str]) -> bool:
    """
    Whether `apps` still takes an application that played: one without a channel for the `hold` of the pool, one of a
    channel only while the channel is present (its `absent_after`), so the pool never keeps the channel longer.
    """
    owner = owner_of(scene, app)
    return owner is None or owner in present


def pool_present(scene: Scene, pool: str, observation: Observation, present: frozenset[str]) -> bool:
    """
    Whether a pool has members, counted before slots are assigned (so conditions never depend on the result): `apps`
    while anything plays that it may take (see `held_by_pool`), `people` while anyone is in the voice chat who would
    be one of them (also someone whose `person` channel has a slot of its own), `auto` while either is, `devices`
    while an output or input is there that no channel has, a pool of channels while one of them is present.
    """
    if pool == APPS:
        return any(not excluded(scene, app) and held_by_pool(scene, app, present) for app in observation.playing)
    if pool == PEOPLE:
        people = (
            person_channel_of(scene, attendee.name)
            for attendee in observation.people
            if pool_of_person(scene, attendee.name) is None
        )
        return any(channel is None or scene.channels[channel].in_pool for channel in people)
    if pool == AUTO:
        return pool_present(scene, APPS, observation, present) or pool_present(scene, PEOPLE, observation, present)
    if pool == DEVICES:
        return bool(devices_of(scene, observation))
    config = scene.pools[pool]
    if isinstance(config, AppsPoolConfig):
        return any(
            not app_matches(app, expand(config.exclude, Kind.STREAMS)) for app in observation.pool_playing.get(pool, ())
        )
    if isinstance(config, PeoplePoolConfig):
        names = {name.lower() for name in config.people}
        return any(attendee.name.lower() in names for attendee in observation.people)
    return any(channel in present for channel in scene.channels_of(pool))


class Presence:
    """The channels that are present, each kept `absent_after` seconds after it had nothing to control any more."""

    def __init__(self, scene: Scene):
        self.scene = scene
        self._delayed = {name: Delayed(0.0, channel.absent_after) for name, channel in scene.channels.items()}

    def carry(self, before: Presence) -> None:
        """Goes on from where `before` was (a reload): the channels with the same id."""
        for name, delayed in self._delayed.items():
            if name in before._delayed:
                delayed.carry(before._delayed[name])

    def update(self, observation: Observation, now: float) -> frozenset[str]:
        for name, delayed in self._delayed.items():
            delayed.update(present_now(name, self.scene.channels[name], observation), now)
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
    The observation the pools see: the applications stay `[pool.apps] hold` after they stopped, the devices
    `[pool.devices] hold` after they went, the people `absent_after` after they left the voice chat (like the
    channels).
    """

    def __init__(self, scene: Scene, absent_after: float):
        self._playing = Lingering[str](scene.apps.hold)
        self._devices = Lingering[SoundDevice](scene.devices.hold, lambda gone, new: gone.name == new.name)
        # a reconnect gets a new id: the same name takes the place of who left
        self._people = Lingering[Attendee](absent_after, lambda gone, new: gone.name == new.name)
        self._pools: dict[str, Lingering[str]] = {}
        """The applications each pool of applications of your own holds (`hold` of its own)."""
        for name in scene.apps_pools:
            pool = scene.pools[name]
            assert isinstance(pool, AppsPoolConfig)
            self._pools[name] = Lingering[str](pool.hold)
        self._matches = {
            name: expand(pool.match, Kind.STREAMS)
            for name in scene.apps_pools
            if isinstance(pool := scene.pools[name], AppsPoolConfig)
        }

    def carry(self, before: PoolMembers) -> None:
        """Goes on from where `before` was (a reload)."""
        self._playing.carry(before._playing)
        for name, lingering in self._pools.items():
            if name in before._pools:
                lingering.carry(before._pools[name])
        self._devices.carry(before._devices)
        self._people.carry(before._people)

    def update(self, observation: Observation, now: float) -> Observation:
        pool_playing = {
            name: lingering.update(
                tuple(app for app in observation.playing if app_matches(app, self._matches[name])), now
            )
            for name, lingering in self._pools.items()
        }
        return replace(
            observation,
            pool_playing=pool_playing,
            playing=self._playing.update(observation.playing, now),
            people=self._people.update(observation.people, now),
            sound_devices=self._devices.update(observation.sound_devices, now),
        )

    def deadline(self) -> float | None:
        deadlines = (
            self._playing.deadline(),
            self._people.deadline(),
            self._devices.deadline(),
            *(lingering.deadline() for lingering in self._pools.values()),
        )
        return min((d for d in deadlines if d is not None), default=None)
