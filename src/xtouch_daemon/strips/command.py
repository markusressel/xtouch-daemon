"""
A fader or an encoder that sets a value with a program of your own (`{ command = { ... } }` in `[controls]`), e.g. the
brightness of a screen: `set` runs with the new value, `watch` tells the value when something else changes it.
"""

import asyncio
import logging
import re
from collections.abc import Callable

from xtouch_daemon.hardware.protocol import RingMode
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.slots.model import VALUE, CommandControl
from xtouch_daemon.strips.knobs import ring_position
from xtouch_daemon.system.commands import CommandError, Commands

_LOGGER = logging.getLogger(__name__)

WATCH_RESTART = 5.0
"""Seconds before a `watch` program that ended or could not start runs again."""
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def value_text(value: float) -> str:
    """A value for `{value}`: without an exponent and without trailing zeros, e.g. `0.6`, `42`."""
    return f"{round(value, 6):.6f}".rstrip("0").rstrip(".")


def parse_value(line: str) -> float | None:
    """The first number of a line that `watch` printed, e.g. 0.6 of `0.60` or of `brightness: 0.60`."""
    match = NUMBER.search(line)
    return float(match.group()) if match is not None else None


class CommandLink:
    """
    The value of a command control on a fader or an encoder. Moves and turns set it at once on the device; `set` runs
    with the newest value only, as programs are slower than hands. `on_change` is called when `watch` changed it.
    """

    def __init__(
        self,
        strip: Strip,
        config: CommandControl,
        commands: Commands,
        encoder_step: int,
        what: str,
        on_change: Callable[[], None],
    ):
        self.strip = strip
        self.config = config
        self.commands = commands
        self.what = what
        self.on_change = on_change
        self.low, self.high = config.range
        self.step = config.step if config.step is not None else (self.high - self.low) * encoder_step / 100
        self.value: float | None = None
        """The value: the one set last, or the one `watch` printed last; None before either."""
        self.touched = False
        self._wanted: float | None = None
        """The value to set next, None while there is none."""
        self._setter: asyncio.Task[None] | None = None
        self._watcher = (
            commands.start(self._watch(config.watch), f"{what}: watch") if config.watch is not None else None
        )

    def fraction(self) -> float | None:
        """Where the value is in the range: 0 at the bottom, 1 at the top."""
        if self.value is None:
            return None
        return max(0.0, min(1.0, (self.value - self.low) / (self.high - self.low)))

    # -- the encoder ----------------------------------------------------------------------------------------------

    def ring(self) -> tuple[int, RingMode]:
        fraction = self.fraction()
        return (0, RingMode.DOT) if fraction is None else (ring_position(fraction), RingMode.WRAP)

    def turn(self, steps: int) -> None:
        """Changes the value by `step` per step: from the value, else from `push`, else from the bottom."""
        start = self.value if self.value is not None else self.config.push
        start = start if start is not None else self.low
        self.set(start + steps * self.step)
        self.strip.set_ring(*self.ring())

    def push(self, pressed: bool) -> None:
        if pressed and self.config.push is not None:
            self.set(self.config.push)
            self.strip.set_ring(*self.ring())

    # -- the fader ------------------------------------------------------------------------------------------------

    def show_fader(self) -> None:
        if not self.touched and (fraction := self.fraction()) is not None:
            self.strip.set_fader(fraction)

    def moved(self, fraction: float) -> None:
        # in steps of 0.1 % of the range: finer than a hand, and no noise of the fader's resolution in the value
        self.set(self.low + round(fraction, 3) * (self.high - self.low))

    def touch(self, touched: bool) -> None:
        self.touched = touched
        # let go, it stays where the hand left it
        self.show_fader()

    # -- the programs ---------------------------------------------------------------------------------------------

    def set(self, value: float) -> None:
        """Sets the value (within the range): on the device at once, with `set` as soon as the one before is done."""
        self.value = self._wanted = round(max(self.low, min(self.high, value)), 6)
        if self._setter is None:
            self._setter = self.commands.start(self._set(), f"{self.what}: set")

    async def _set(self) -> None:
        try:
            while (value := self._wanted) is not None:
                self._wanted = None
                argv = [part.replace(VALUE, value_text(value)) for part in self.config.set]
                try:
                    await self.commands.run(argv)
                except CommandError as e:
                    _LOGGER.warning(f"{self.what}: setting {value_text(value)}: {e}")
        finally:
            self._setter = None

    async def _watch(self, argv: tuple[str, ...]) -> None:
        while True:
            try:
                async for line in self.commands.lines(argv):
                    value = parse_value(line)
                    # while a value is set or the fader is under a finger, the hand knows better
                    if value is not None and value != self.value and self._setter is None and not self.touched:
                        self.value = value
                        self.on_change()
                _LOGGER.warning(f"{self.what}: {argv[0]} (watch) ended, again in {WATCH_RESTART:g} s")
            except CommandError as e:
                _LOGGER.warning(f"{self.what}: watch: {e}, again in {WATCH_RESTART:g} s")
            await asyncio.sleep(WATCH_RESTART)

    def close(self) -> None:
        for task in (self._watcher, self._setter):
            if task is not None:
                task.cancel()
