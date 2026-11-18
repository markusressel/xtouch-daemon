"""
Who tells the participants of a voice chat: a `VoipProvider` keeps a snapshot of them (who is there, who talks, their
volume and level), tells its listeners when it changed, and carries out volume and mute commands. The `voip` strips
show the snapshot; they don't know which voice chat it comes from.

Voice chat clients mix every participant into one stream, so the sound server can't tell them apart: a provider asks
the client (or a plugin inside it). See docs/development/design/voice-chat.md for what the clients offer.

The provider remembers the volume and the mute the strips set for each name (`change_volume()`, `change_muted()`),
and sets them again when someone of that name comes back: the clients forget them when a participant leaves (the
Mumble plugin keeps them per session). A mute changed in the client itself (Mumble's local mute) replaces the one the
strips set, so it is not undone when the person comes back.
"""

import abc
import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum

_LOGGER = logging.getLogger(__name__)

VOLUME_LIMIT = 200
"""The loudest volume of a participant, in percent."""


class Capability(StrEnum):
    """What a provider can do besides telling who is there and who talks."""

    VOLUME = "volume"
    """Tell and set the volume of each participant."""
    MUTE = "mute"
    """Tell and set whether a participant is muted (for the user only)."""
    LEVELS = "levels"
    """Tell how loud each participant talks right now."""


@dataclass(frozen=True)
class Participant:
    id: str
    """What the provider knows the participant by; stays the same while they are there."""
    name: str
    talking: bool = False
    muted: bool = False
    """Muted for the user (locally), not by the server."""
    volume: int = 100
    """The volume of the participant for the user, in percent."""
    level: float | None = None
    """
    How loud they talk right now (the peak since the last snapshot, after their volume), 0..1; None if the provider
    can't tell.
    """
    pre_fader_level: float | None = None
    """The same before their volume; None if the provider can't tell (then `level` stands in)."""


type Listener = Callable[[], None]


@dataclass
class _Kept:
    """What the strips set for a name: they get it again when they come back."""

    volume: int | None = None
    muted: bool | None = None


class VoipProvider(abc.ABC):
    """The participants of a voice chat, see the module."""

    name: str = "voip"

    def __init__(self, capabilities: frozenset[Capability] = frozenset()):
        self.participants: tuple[Participant, ...] = ()
        """Who is there, in the order they came."""
        self.connected = False
        """Whether the provider knows the voice chat right now (e.g. a client is connected)."""
        self.capabilities = capabilities
        self.client: str | None = None
        """The voice chat client, e.g. "mumble", if the provider knows it."""
        self.channel: str | None = None
        """The channel of the user in the voice chat, if the provider knows it."""
        self._listeners: list[Listener] = []
        self._kept: dict[str, _Kept] = {}
        """What the strips set, by the name of the participant in lower case (`str.casefold()`)."""
        self._restoring: set[asyncio.Task[None]] = set()

    def subscribe(self, listener: Listener) -> None:
        """Calls `listener` after every change."""
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def update(self, participants: tuple[Participant, ...], connected: bool = True) -> None:
        """A new snapshot; the listeners hear of it if it differs."""
        if participants == self.participants and connected == self.connected:
            return
        before = {participant.id: participant for participant in self.participants}
        self.participants = participants
        self.connected = connected
        for listener in list(self._listeners):
            listener()
        for participant in participants:
            previous = before.get(participant.id)
            if previous is None:
                self._restore(participant)
            elif previous.muted != participant.muted:
                self._follow_mute(participant)

    def _restore(self, participant: Participant) -> None:
        """Sets what the strips set for the name of someone who came (back), if it differs."""
        kept = self._kept.get(participant.name.casefold())
        if kept is None:
            return
        if kept.volume is not None and kept.volume != participant.volume:
            self._in_background(self.set_volume(participant.id, kept.volume))
        if kept.muted is not None and kept.muted != participant.muted:
            self._in_background(self.set_muted(participant.id, kept.muted))

    def _follow_mute(self, participant: Participant) -> None:
        """Keeps a mute changed in the client (e.g. Mumble's local mute) instead of what the strips set before."""
        kept = self._kept.get(participant.name.casefold())
        if kept is not None and kept.muted is not None:
            kept.muted = participant.muted

    def _in_background(self, command: Coroutine[None, None, None]) -> None:
        task = asyncio.get_running_loop().create_task(command)
        self._restoring.add(task)
        task.add_done_callback(self._restoring.discard)

    def _keep(self, participant_id: str) -> _Kept | None:
        participant = self.participant(participant_id)
        if participant is None:
            return None
        return self._kept.setdefault(participant.name.casefold(), _Kept())

    async def change_volume(self, participant_id: str, volume: int) -> None:
        """Sets the volume of a participant (`set_volume()`) and keeps it for their name."""
        kept = self._keep(participant_id)
        if kept is not None:
            kept.volume = volume
        await self.set_volume(participant_id, volume)

    async def change_muted(self, participant_id: str, muted: bool) -> None:
        """Mutes a participant (`set_muted()`) and keeps it for their name."""
        kept = self._keep(participant_id)
        if kept is not None:
            kept.muted = muted
        await self.set_muted(participant_id, muted)

    def participant(self, participant_id: str) -> Participant | None:
        return next((each for each in self.participants if each.id == participant_id), None)

    @abc.abstractmethod
    async def run(self) -> None:
        """Follows the voice chat until cancelled."""

    @abc.abstractmethod
    async def set_volume(self, participant_id: str, volume: int) -> None:
        """Sets the volume of a participant for the user (percent, 0..VOLUME_LIMIT); only with `Capability.VOLUME`."""

    @abc.abstractmethod
    async def set_muted(self, participant_id: str, muted: bool) -> None:
        """Mutes a participant for the user; only with `Capability.MUTE`."""
