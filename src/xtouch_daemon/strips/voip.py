"""
`voip` strips: the participants of the voice chat, one per strip, from the provider of `[voip]`. A `voip` strip with
`count = N` takes N places, a `VoipGroup`; with more participants than places, Select on any of them shows the next
page of them, as the bank buttons of a DAW do.
"""

import asyncio
import math
from collections.abc import Callable

from xtouch_daemon import protocol
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import VoipStripConfig, color_of
from xtouch_daemon.launch import LaunchButton
from xtouch_daemon.protocol import Button, Color, Led
from xtouch_daemon.strips.base import NOTICE_TIME, StripController, StripEnv
from xtouch_daemon.surface import Strip
from xtouch_daemon.voip.provider import Capability, Participant, VoipProvider


class VoipGroup:
    """The places of one `voip` strip, and which page of the participants they show."""

    def __init__(
        self,
        provider: VoipProvider,
        size: int,
        refresh: Callable[[], None] = lambda: None,
        launch: LaunchButton | None = None,
        processes: Callable[[], frozenset[str]] = frozenset,
    ):
        """`processes` are the names of the processes that run, for `launch`."""
        self.provider = provider
        self.size = size
        self.page = 0
        self.refresh = refresh
        """Shows the strips again, after the page changed."""
        self.launch = launch
        """What Select starts while the voice chat is not there (`launch`), for all places of the group."""
        self._processes = processes

    @property
    def runs(self) -> bool:
        """Whether the voice chat is there: its plugin reports it (also while nobody talks), or its program runs."""
        return self.provider.connected or (self.launch is not None and self.launch.program_runs(self._processes()))

    def select(self) -> str | None:
        """
        Select on one of the places: launches the voice chat while it is not there (with `launch`), and shows the
        next page otherwise. What to show for a moment, e.g. "pg 2/3"; None after a launch.
        """
        if self.launch is not None and not self.runs:
            if self.launch.press(False):
                self.refresh()
            return None
        return self.next_page()

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.provider.participants) / self.size))

    def participant(self, slot: int) -> Participant | None:
        """Who the place `slot` (from 0) shows on the current page."""
        index = self.page % self.pages * self.size + slot
        participants = self.provider.participants
        return participants[index] if index < len(participants) else None

    def next_page(self) -> str:
        """Shows the next page (after the last one the first), and says which, e.g. "pg 2/3"."""
        self.page = (self.page % self.pages + 1) % self.pages
        self.refresh()
        return f"pg {self.page + 1}/{self.pages}"


class VoipStrip(StripController):
    """One place of a `VoipGroup`: the fader sets the participant's volume, Mute mutes them, Select pages."""

    def __init__(self, strip: Strip, env: StripEnv, group: VoipGroup, slot: int, config: VoipStripConfig):
        super().__init__(strip, env, color_of(config.color), config.meter)
        self.group = group
        self.slot = slot
        self.talking_color = color_of(config.talking_color)
        self.max_volume = config.max_volume
        self.notice: str | None = None
        self._notice_timer: asyncio.TimerHandle | None = None
        self._wanted: int | None = None
        """The volume the fader set last, shown until the provider reports one."""

    @property
    def provider(self) -> VoipProvider:
        return self.group.provider

    @property
    def participant(self) -> Participant | None:
        return self.group.participant(self.slot)

    def can(self, capability: Capability) -> bool:
        return capability in self.provider.capabilities

    def update(self, state: AudioState) -> None:
        self.show()

    @property
    def launches(self) -> bool:
        return self.group.launch is not None

    def show(self) -> None:
        person = self.participant
        paging = self.group.pages > 1
        launch = self.group.launch
        launching = launch is not None and launch.launching(self.group.runs)
        self.strip.set_led(Button.SELECT, Led.FLASH if launching else Led.ON if paging else Led.OFF)
        self.strip.set_led(Button.REC, Led.OFF)
        self.strip.set_led(Button.SOLO, Led.OFF)
        self.strip.set_ring(0)
        if person is None:
            self.strip.set_color(Color.BLACK)
            self.strip.set_text(0, "")
            self.strip.set_text(1, self.notice or "")
            self.strip.set_led(Button.MUTE, Led.OFF)
            self.strip.park()
            return
        self.strip.set_color(self.talking_color if person.talking else self.color)
        self.strip.set_text(0, person.name)
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
        self.run_command(self.provider.set_volume(person.id, volume), f"volume of {person.name}")

    def on_touch(self, touched: bool) -> None:
        if not touched:
            # back to where the participant's volume is (or goes)
            self.show()

    def on_button(self, button: Button, pressed: bool) -> None:
        if not pressed:
            return
        match button:
            case Button.SELECT:
                notice = self.group.select()
                if notice is not None:
                    self.notify(notice)
            case Button.MUTE:
                person = self.participant
                if person is not None and self.can(Capability.MUTE):
                    self.run_command(self.provider.set_muted(person.id, not person.muted), f"mute {person.name}")
            case _:
                pass

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
