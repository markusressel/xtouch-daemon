"""
What the encoder of a volume strip does (its `encoder` option): a knob turns, is pushed, and lights its ring.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.protocol import RING_MAX, RingMode

if TYPE_CHECKING:
    from xtouch_daemon.media import Player
    from xtouch_daemon.strips.apps import AppStrip, AutoStrip
    from xtouch_daemon.strips.base import VolumeStrip

_LOGGER = logging.getLogger(__name__)

SEEK_STEP = 5.0
"""Seconds one step of the encoder seeks in a track."""
PROGRESS_INTERVAL = 1.0
"""How often the ring shows how far the track is."""
BALANCE_STEP = 0.05
"""How far one step of the encoder moves the balance (from the center to one side: 20 steps)."""
RING_CENTER = (RING_MAX + 1) // 2


def ring_position(fraction: float) -> int:
    """The position of the ring for 0 (the first LED) .. 1 (the last one)."""
    return round(max(0.0, min(1.0, fraction)) * (RING_MAX - 1)) + 1


class Knob:
    """The encoder of a strip that has something to control (the strip calls these only while it is active)."""

    idle_too = False
    """Whether it works while the strip is idle (dark) too."""

    def __init__(self, owner: VolumeStrip):
        self.owner = owner

    def turn(self, steps: int) -> None:
        pass

    def push(self, pressed: bool) -> None:
        pass

    def ring(self) -> tuple[int, RingMode]:
        """What the ring shows: a position (0: off) and a mode."""
        return 0, RingMode.DOT

    def close(self) -> None:
        """The strip is taken over by another configuration."""


class VolumeKnob(Knob):
    """Fine steps of the volume (`behavior.encoder_step`), a push sets `behavior.reset_volume`."""

    def turn(self, steps: int) -> None:
        self.owner.step_volume(steps)

    def push(self, pressed: bool) -> None:
        if pressed:
            self.owner.reset_volume()

    def ring(self) -> tuple[int, RingMode]:
        return self.owner.volume_ring()


class BalanceKnob(Knob):
    """
    The balance between left and right, shown from the center of the ring; a push centers it. Nothing for mono
    devices and streams. Turns come faster than the sound server carries them out: only the latest is set.
    """

    def __init__(self, owner: VolumeStrip):
        super().__init__(owner)
        self.wanted: float | None = None
        self._setting = False

    @property
    def current(self) -> float | None:
        if self.wanted is not None:
            return self.wanted
        return None if self.owner.level is None else self.owner.level.balance

    def turn(self, steps: int) -> None:
        if (current := self.current) is not None:
            self._set(round(max(-1.0, min(1.0, current + steps * BALANCE_STEP)), 2))

    def push(self, pressed: bool) -> None:
        if pressed and self.current is not None:
            self._set(0.0)

    def ring(self) -> tuple[int, RingMode]:
        if (current := self.current) is None:
            return 0, RingMode.DOT
        # from the center, rounding halves away from it, so both sides look alike
        offset = current * (RING_CENTER - 1)
        steps = int(abs(offset) + 0.5)
        return RING_CENTER + (steps if offset > 0 else -steps), RingMode.BOOST_CUT

    def _set(self, balance: float) -> None:
        self.wanted = balance
        self.owner.strip.set_ring(*self.ring())
        if not self._setting:
            self._setting = True
            self.owner.run_command(self._apply(), "balance")

    async def _apply(self) -> None:
        try:
            while self.wanted is not None:
                balance = self.wanted
                try:
                    await self.owner.apply_balance(balance)
                except AudioCommandError as e:
                    _LOGGER.warning(f"Strip {self.owner.strip.index + 1}: setting the balance: {e}")
                if self.wanted == balance:
                    self.wanted = None
        finally:
            self._setting = False


class PickKnob(Knob):
    """
    Picks the application of an `auto` strip among those without a strip of their own (also while the strip has none
    yet); a push pins it, so it stays after it stopped playing. The ring shows which of them it is, pinned up to there.
    """

    idle_too = True

    def __init__(self, owner: AutoStrip):
        super().__init__(owner)
        self.auto = owner

    def turn(self, steps: int) -> None:
        if self.auto.slot is not None:
            self.auto.slot.pick(steps)

    def push(self, pressed: bool) -> None:
        if pressed and self.auto.slot is not None:
            self.auto.slot.toggle_pin()

    def ring(self) -> tuple[int, RingMode]:
        slot = self.auto.slot
        position = slot.position() if slot is not None else None
        if slot is None or position is None:
            return 0, RingMode.DOT
        index, count = position
        fraction = index / (count - 1) if count > 1 else 0.0
        return ring_position(fraction), RingMode.WRAP if slot.pinned else RingMode.DOT


class MediaKnob(Knob):
    """
    The media player of the applications of the strip (MPRIS, see `media.py`): turning seeks by `SEEK_STEP`, a push
    plays or pauses, and the ring shows how far the track is. Nothing for applications without a player.
    """

    def __init__(self, owner: AppStrip):
        super().__init__(owner)
        self.apps = owner
        self.progress: float | None = None
        self._poller: asyncio.Task[None] | None = None

    def player(self) -> Player | None:
        players = self.apps.env.players
        if players is None:
            return None
        from xtouch_daemon.media import player_of

        return player_of(players.players, self.apps.streams.values())

    def turn(self, steps: int) -> None:
        players, player = self.apps.env.players, self.player()
        if players is not None and player is not None:
            self.apps.run_command(players.seek(player, steps * SEEK_STEP), "seek")

    def push(self, pressed: bool) -> None:
        players, player = self.apps.env.players, self.player()
        if pressed and players is not None and player is not None:
            self.apps.run_command(players.play_pause(player), "play/pause")

    def ring(self) -> tuple[int, RingMode]:
        if self._poller is None and self.apps.env.players is not None:
            self._poller = asyncio.create_task(self._poll(), name=f"strip {self.apps.strip.index + 1}: track")
        if self.progress is None:
            return 0, RingMode.DOT
        return ring_position(self.progress), RingMode.DOT

    async def _poll(self) -> None:
        players = self.apps.env.players
        assert players is not None, "polls only with players"
        while True:
            player = self.player() if self.apps.active else None
            progress = None
            if player is not None:
                with contextlib.suppress(AudioCommandError):
                    progress = await players.progress(player)
            if progress != self.progress:
                self.progress = progress
                if self.apps.active:
                    self.apps.strip.set_ring(*self.ring())
            await asyncio.sleep(PROGRESS_INTERVAL)

    def close(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
