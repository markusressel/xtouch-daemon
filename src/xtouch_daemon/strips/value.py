"""
What the bindings of programs of your own do on a strip (`config.bindings`): a value that `set` changes and `watch`
tells (`CommandValue`, a `BoundValue` as the values of entities are), the lines of a `watch` (`WatchedLine`), a program
a button runs (`run_program()`), and how a line becomes a value, an LED, a color or a level. `ValueSource` is what has
values for the faders and encoders of `[controls]`: a `custom` channel. The same for entities of Home Assistant is in
`strips.entity`.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, get_args

from xtouch_daemon.config.bindings import EntityValueBinding, ValueBinding, fill
from xtouch_daemon.config.values import ColorName
from xtouch_daemon.hardware.protocol import Led, RingMode
from xtouch_daemon.strips.knobs import ring_position
from xtouch_daemon.system.commands import CommandError, Commands

_LOGGER = logging.getLogger(__name__)

WATCH_RESTART = 5.0
"""Seconds before a `watch` program that ended or could not start runs again."""
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
LIT = frozenset({"on", "1", "true", "yes"})
"""The lines of a `watch` that light an LED; `flash` flashes it, anything else turns it off."""
COLOR_NAMES: frozenset[str] = frozenset(get_args(ColorName))


def value_text(value: float) -> str:
    """A value for `{value}`: without an exponent and without trailing zeros, e.g. `0.6`, `42`."""
    return f"{round(value, 6):.6f}".rstrip("0").rstrip(".")


def parse_value(line: str) -> float | None:
    """The first number of a line that `watch` printed, e.g. 0.6 of `0.60` or of `brightness: 0.60`."""
    match = NUMBER.search(line)
    return float(match.group()) if match is not None else None


def led_of_line(line: str) -> Led:
    """An LED for a line of a `watch`: on for `on`, `1`, `true`, `yes`, flashing for `flash`, else off (any case)."""
    word = line.strip().lower()
    if word == "flash":
        return Led.FLASH
    return Led.ON if word in LIT else Led.OFF


def color_of_line(line: str) -> ColorName | None:
    """The color a line of a `watch` names (any case), None for a line that is no color name."""
    word = line.strip().lower()
    return word if word in COLOR_NAMES else None  # type: ignore[return-value]


def level_of_line(line: str, low: float, high: float) -> float | None:
    """Where the number of a line of a `watch` is between `low` and `high`, from 0 to 1; None without a number."""
    number = parse_value(line)
    if number is None:
        return None
    return max(0.0, min(1.0, (number - low) / (high - low)))


def run_program(commands: Commands, argv: Sequence[str], what: str) -> None:
    """Runs a program in a task of `commands`, to its end; a problem is logged as a warning, for `what`."""

    async def run() -> None:
        try:
            await commands.run(argv)
        except CommandError as e:
            _LOGGER.warning(f"{what}: {e}")

    commands.start(run(), f"{what}: run")


async def watch_lines(commands: Commands, argv: Sequence[str], what: str, on_line: Callable[[str], None]) -> None:
    """
    Runs a `watch` program and calls `on_line` with each line it prints, until cancelled: again WATCH_RESTART seconds
    after it ended or could not start.
    """
    while True:
        try:
            async for line in commands.lines(argv):
                on_line(line)
            _LOGGER.warning(f"{what}: {argv[0]} (watch) ended, again in {WATCH_RESTART:g} s")
        except CommandError as e:
            _LOGGER.warning(f"{what}: watch: {e}, again in {WATCH_RESTART:g} s")
        await asyncio.sleep(WATCH_RESTART)


class WatchedLine:
    """
    The newest line of a `watch` program, for as long as it lives (until `close()`; see `watch_lines()`). Its
    listeners are called when the line changed. `strips.entity.EntityLine` is the same for an entity.
    """

    def __init__(self, argv: Sequence[str], commands: Commands, what: str):
        self.argv = tuple(argv)
        self.source: tuple[object, ...] = ("watch", self.argv)
        """What it shows the lines of: the same source, the same lines."""
        self.line: str | None = None
        """The line the program printed last; None before the first."""
        self.listeners: list[Callable[[], None]] = []
        self._task = commands.start(watch_lines(commands, self.argv, what, self._printed), f"{what}: watch")

    def _printed(self, line: str) -> None:
        if line != self.line:
            self.line = line
            for listener in list(self.listeners):
                listener()

    def close(self) -> None:
        self._task.cancel()


class BoundValue:
    """
    A value a fader or an encoder sets: of programs of your own (`CommandValue`), or of an entity of Home Assistant
    (`strips.entity.EntityValue`). A move or a turn changes it at once; it is applied (`_apply()`) with the newest value
    only, as programs and services are slower than hands. Its listeners are called when it changed: by a hand, or by
    what it follows (`_follow()`). `what` names it in the log.
    """

    def __init__(
        self,
        binding: ValueBinding | EntityValueBinding,
        commands: Commands,
        encoder_step: int,
        what: str,
        low: float,
        high: float,
    ):
        self.binding = binding
        self.commands = commands
        self.what = what
        self._encoder_step = encoder_step
        self.low, self.high = low, high
        self.step = self._step()
        self.value: float | None = (self.low + self.high) / 2 if commands.simulated else None
        """The value: the one set last, or the one it follows; None before either."""
        self._touches = 0
        """How many faders that set it are under a finger (two slots can show one value)."""
        self.listeners: list[Callable[[], None]] = []
        self._wanted: float | None = None
        """The value to set next, None while there is none."""
        self._setter: asyncio.Task[None] | None = None

    def _step(self) -> float:
        step = self.binding.step
        return step if step is not None else (self.high - self.low) * self._encoder_step / 100

    def set_range(self, low: float, high: float) -> None:
        """Another range (an entity told its own): the step follows it."""
        self.low, self.high = low, high
        self.step = self._step()

    def fraction(self) -> float | None:
        """Where the value is between `min` and `max`: 0 at the bottom, 1 at the top."""
        if self.value is None:
            return None
        return max(0.0, min(1.0, (self.value - self.low) / (self.high - self.low)))

    def ring(self) -> tuple[int, RingMode]:
        fraction = self.fraction()
        return (0, RingMode.DOT) if fraction is None else (ring_position(fraction), RingMode.WRAP)

    def text(self) -> str:
        """The value for the LCD, in `format`; empty while it is not known."""
        return "" if self.value is None else self.binding.format.format(value=self.value)

    # -- hands ----------------------------------------------------------------------------------------------------

    @property
    def touched(self) -> bool:
        """Whether a fader that sets it is under a finger."""
        return self._touches > 0

    def touch(self, touched: bool) -> None:
        """A finger on a fader that sets it (True) or off it (False): it is touched while any finger is on one."""
        self._touches = self._touches + 1 if touched else max(0, self._touches - 1)

    def turn(self, steps: int) -> None:
        """Changes the value by `step` per step: from the value, else from `push`, else from `min`."""
        start = self.value if self.value is not None else self.binding.push
        self.set((start if start is not None else self.low) + steps * self.step)

    def push(self, pressed: bool) -> None:
        if pressed and self.binding.push is not None:
            self.set(self.binding.push)

    def moved(self, fraction: float) -> None:
        # in steps of 0.1 % of the range: finer than a hand, and no noise of the fader's resolution in the value
        self.set(self.low + round(fraction, 3) * (self.high - self.low))

    # -- applying it ----------------------------------------------------------------------------------------------

    def set(self, value: float) -> None:
        """Sets the value (between `min` and `max`): at once here, applied as soon as the one before is."""
        self.value = self._wanted = round(max(self.low, min(self.high, value)), 6)
        if self._setter is None:
            self._setter = self.commands.start(self._set(), f"{self.what}: set")
        self._changed()

    def _changed(self) -> None:
        for listener in list(self.listeners):
            listener()

    async def _set(self) -> None:
        try:
            while (value := self._wanted) is not None:
                self._wanted = None
                await self._apply(value)
        finally:
            self._setter = None

    async def _apply(self, value: float) -> None:
        """Applies the value (runs `set`, calls the service); a problem is logged."""
        raise NotImplementedError

    def _follow(self, value: float | None) -> None:
        """What it follows says the value is `value` (None: not known)."""
        # while a value is set or the fader is under a finger, the hand knows better
        if value != self.value and self._setter is None and not self.touched:
            self.value = value
            self._changed()

    def close(self) -> None:
        if self._setter is not None:
            self._setter.cancel()


class CommandValue(BoundValue):
    """
    A value that programs of your own set and watch (`ValueBinding`): `set` runs with the newest value, `watch` prints
    it. `placeholders` fill the programs (`{target}`).
    """

    binding: ValueBinding

    def __init__(
        self,
        binding: ValueBinding,
        commands: Commands,
        encoder_step: int,
        what: str,
        placeholders: Mapping[str, str] | None = None,
    ):
        super().__init__(binding, commands, encoder_step, what, binding.min, binding.max)
        self.placeholders = dict(placeholders or {})
        self._watcher = (
            commands.start(
                watch_lines(commands, fill(binding.watch, **self.placeholders), what, self._printed), f"{what}: watch"
            )
            if binding.watch is not None
            else None
        )

    async def _apply(self, value: float) -> None:
        argv = fill(self.binding.set, **self.placeholders, value=value_text(value))
        try:
            await self.commands.run(argv)
        except CommandError as e:
            _LOGGER.warning(f"{self.what}: setting {value_text(value)}: {e}")

    def _printed(self, line: str) -> None:
        if (value := parse_value(line)) is not None:
            self._follow(value)

    def close(self) -> None:
        super().close()
        if self._watcher is not None:
            self._watcher.cancel()


class ValueSource(Protocol):
    """
    What has values for the faders and encoders of `[controls]` (`{ channel = "..." }`): a `custom` channel. Its
    values change when it switches to another target; then it calls its listeners.
    """

    listeners: list[Callable[[], None]]
    """Called when the values are others (the target switched)."""

    def fader_value(self) -> BoundValue | None:
        """The value of its fader, None without one."""
        ...

    def encoder_value(self) -> BoundValue | None:
        """The value of its own encoder, None without one (an encoder of `[controls]` takes the fader's then)."""
        ...
