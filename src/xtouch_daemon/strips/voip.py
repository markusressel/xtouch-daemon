"""
`voip` strips: the participants of the voice chat, one per strip, from the provider of `[voip]`. A strip with `person`
always shows that person (dark while they are not there). The other `voip` strips of a layout are its group: they
show the participants without a strip of their own, in the order of the provider and of the strips; with more
participants than strips, Select on any of them shows the next page of them, as the bank buttons of a DAW do.
"""

import asyncio
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from xtouch_daemon import protocol
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import VoipStripConfig, color_of
from xtouch_daemon.launch import LaunchButton
from xtouch_daemon.protocol import Button, Color, Led
from xtouch_daemon.strips.base import NOTICE_TIME, StripController, StripEnv
from xtouch_daemon.surface import Strip
from xtouch_daemon.voip.provider import Capability, Participant, VoipProvider


@dataclass(frozen=True)
class _Assignment:
    """Who the strips show, for one snapshot of the provider."""

    fixed: dict[int, Participant]
    """The participant of each seat with `person` whose person is there."""
    rest: tuple[Participant, ...]
    """The participants without a strip of their own, for the group."""


class VoipSeats:
    """
    The `voip` strips of a layout (its seats, in the order of the configuration), who each of them shows, and which
    page of the participants the group shows.
    """

    def __init__(
        self, provider: VoipProvider, persons: Sequence[tuple[str, ...]], refresh: Callable[[], None] = lambda: None
    ):
        """`persons` are the `person` names of each seat, none for the seats of the group."""
        self.provider = provider
        self.persons = tuple(frozenset(name.casefold() for name in names) for names in persons)
        self.group = tuple(seat for seat, names in enumerate(self.persons) if not names)
        """The seats of the group, in order."""
        self.page = 0
        self.refresh = refresh
        """Shows the strips again, after the page changed."""
        self._assigned: tuple[tuple[Participant, ...], _Assignment] | None = None
        """The assignment of the last snapshot of the provider."""

    def _assignment(self) -> _Assignment:
        participants = self.provider.participants
        if self._assigned is not None and self._assigned[0] is participants:
            return self._assigned[1]
        fixed: dict[int, Participant] = {}
        taken: set[str] = set()
        for seat, names in enumerate(self.persons):
            found = next(
                (each for each in participants if each.name.casefold() in names and each.id not in taken), None
            )
            if found is not None:
                fixed[seat] = found
                taken.add(found.id)
        assignment = _Assignment(fixed, tuple(each for each in participants if each.id not in taken))
        self._assigned = (participants, assignment)
        return assignment

    def fixed(self, seat: int) -> bool:
        """Whether the seat has a `person`."""
        return bool(self.persons[seat])

    @property
    def pages(self) -> int:
        """The pages of the group."""
        if not self.group:
            return 1
        return max(1, math.ceil(len(self._assignment().rest) / len(self.group)))

    def participant(self, seat: int) -> Participant | None:
        """Who the seat shows: its person, or for a seat of the group, who it shows on the current page."""
        assignment = self._assignment()
        if self.fixed(seat):
            return assignment.fixed.get(seat)
        index = self.page % self.pages * len(self.group) + self.group.index(seat)
        return assignment.rest[index] if index < len(assignment.rest) else None

    def next_page(self) -> str:
        """Shows the next page of the group (after the last one the first), and says which, e.g. "pg 2/3"."""
        self.page = (self.page % self.pages + 1) % self.pages
        self.refresh()
        return f"pg {self.page + 1}/{self.pages}"


@dataclass(frozen=True)
class VoipSeat:
    """Where a `voip` strip sits: the seats of its layout, its own among them, and what its Select starts."""

    seats: VoipSeats
    seat: int
    launch: LaunchButton | None = None
    """Shared by the `voip` strips of the layout with the same command (`launch`), so a press starts it once."""


class VoipStrip(StripController):
    """
    A seat of the `voip` strips: the fader sets the participant's volume, Mute mutes them, Select pages the group (or
    starts the voice chat, with `launch`).
    """

    def __init__(self, strip: Strip, env: StripEnv, seat: VoipSeat, config: VoipStripConfig):
        super().__init__(strip, env, color_of(config.color), config.meter)
        self.seats = seat.seats
        self.seat = seat.seat
        self.launch = seat.launch
        self.name = config.title
        """The top line of a strip with `person`, "" for one of the group."""
        self.talking_color = color_of(config.talking_color)
        self.max_volume = config.max_volume
        self.notice: str | None = None
        self._notice_timer: asyncio.TimerHandle | None = None
        self._wanted: int | None = None
        """The volume the fader set last, shown until the provider reports one."""

    @property
    def provider(self) -> VoipProvider:
        return self.seats.provider

    @property
    def fixed(self) -> bool:
        """Whether the strip shows one person (`person`) rather than one of the group."""
        return self.seats.fixed(self.seat)

    @property
    def participant(self) -> Participant | None:
        return self.seats.participant(self.seat)

    def can(self, capability: Capability) -> bool:
        return capability in self.provider.capabilities

    def update(self, state: AudioState) -> None:
        self.show()

    @property
    def launches(self) -> bool:
        return self.launch is not None

    @property
    def runs(self) -> bool:
        """Whether the voice chat is there: its plugin reports it (also while nobody talks), or its program runs."""
        return self.provider.connected or (self.launch is not None and self.launch.program_runs(self.env.processes()))

    def absent(self, state: AudioState) -> bool:
        """It shows nobody: its person is not there, or the group has no participant for it."""
        return self.participant is None

    @property
    def title(self) -> str:
        if self.fixed:
            return self.name
        person = self.participant
        return person.name if person is not None else "voip"

    def show(self) -> None:
        person = self.participant
        paging = not self.fixed and self.seats.pages > 1
        launching = self.launch is not None and self.launch.launching(self.runs)
        self.strip.set_led(Button.SELECT, Led.FLASH if launching else Led.ON if paging else Led.OFF)
        self.strip.set_led(Button.REC, Led.OFF)
        self.strip.set_led(Button.SOLO, Led.OFF)
        self.strip.set_ring(0)
        if person is None:
            # dark; a strip with `person` keeps the name, like a device that is not there
            self.strip.set_color(Color.BLACK)
            self.strip.set_text(0, self.name)
            self.strip.set_text(1, self.notice or ("away" if self.fixed else ""))
            self.strip.set_led(Button.MUTE, Led.OFF)
            self.strip.park()
            return
        self.strip.set_color(self.talking_color if person.talking else self.color)
        self.strip.set_text(0, self.name or person.name)
        self.strip.set_led(Button.MUTE, Led.ON if person.muted else Led.OFF)
        if self._wanted == person.volume:
            self._wanted = None
        volume = self._wanted if self._wanted is not None else person.volume
        if self.can(Capability.VOLUME):
            self.strip.set_fader(min(1.0, volume / self.max_volume))
        else:
            self.strip.park()
        if self.notice is not None:
            bottom = self.notice
        elif person.muted:
            bottom = "muted"
        elif self.can(Capability.VOLUME):
            bottom = f"{volume}%"
        else:
            bottom = "talks" if person.talking else ""
        self.strip.set_text(1, bottom)

    def held_meter(self) -> int | None:
        """The participant's level from the provider; without levels a full meter while they talk."""
        person = self.participant
        if not self.meter or person is None:
            return None
        if person.level is not None:
            return round(person.level * protocol.METER_MAX)
        return protocol.METER_MAX - 1 if person.talking else None

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        person = self.participant
        if person is None or not self.can(Capability.VOLUME):
            return
        volume = round(fraction * self.max_volume)
        if volume == (self._wanted if self._wanted is not None else person.volume):
            return
        self._wanted = volume
        self.strip.set_text(1, f"{volume}%")
        self.run_command(self.provider.change_volume(person.id, volume), f"volume of {person.name}")

    def on_touch(self, touched: bool) -> None:
        if not touched:
            # back to where the participant's volume is (or goes)
            self.show()

    def on_button(self, button: Button, pressed: bool) -> None:
        if not pressed:
            return
        match button:
            case Button.SELECT:
                self._select()
            case Button.MUTE:
                person = self.participant
                if person is not None and self.can(Capability.MUTE):
                    self.run_command(self.provider.change_muted(person.id, not person.muted), f"mute {person.name}")
            case _:
                pass

    def _select(self) -> None:
        """Launches the voice chat while it is not there (with `launch`); otherwise a strip of the group pages."""
        if self.launch is not None and not self.runs:
            if self.launch.press(False):
                self.seats.refresh()
        elif not self.fixed:
            self.notify(self.seats.next_page())

    def notify(self, text: str) -> None:
        """Shows `text` on the second line for NOTICE_TIME, e.g. the page."""
        if self._notice_timer is not None:
            self._notice_timer.cancel()
        self.notice = text
        self._notice_timer = asyncio.get_running_loop().call_later(NOTICE_TIME, self._end_notice)
        self.show()

    def _end_notice(self) -> None:
        self._notice_timer = None
        self.notice = None
        self.show()

    def close(self) -> None:
        super().close()
        if self._notice_timer is not None:
            self._notice_timer.cancel()
