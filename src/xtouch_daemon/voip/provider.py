"""
Who tells the participants of a voice chat: a `VoipProvider` keeps a snapshot of them (who is there, who talks, their
volume and level), tells its listeners when it changed, and carries out volume and mute commands. The `voip` strips
show the snapshot; they don't know which voice chat it comes from.

Voice chat clients mix every participant into one stream, so the sound server can't tell them apart: a provider asks
the client (or a plugin inside it). See docs/design/layouts.md for what the clients offer.
"""

import abc
import logging
from collections.abc import Callable
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
    """How loud they talk right now (the peak since the last snapshot), 0..1; None if the provider can't tell."""


type Listener = Callable[[], None]


class VoipProvider(abc.ABC):
    """The participants of a voice chat, see the module."""

    name: str = "voip"

    def __init__(self, capabilities: frozenset[Capability] = frozenset()):
        self.participants: tuple[Participant, ...] = ()
        """Who is there, in the order they came."""
        self.connected = False
        """Whether the provider knows the voice chat right now (e.g. a client is connected)."""
        self.capabilities = capabilities
        self._listeners: list[Listener] = []

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
        self.participants = participants
        self.connected = connected
        for listener in list(self._listeners):
            listener()

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
