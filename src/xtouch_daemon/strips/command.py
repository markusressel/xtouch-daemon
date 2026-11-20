"""
Command channels (`type = "command"`): a value that programs of your own set and watch, e.g. the brightness of a
screen. `set` runs with the new value, `watch` tells the value when something else changes it. The fader and the
encoder of the channel's strip set it, and so do those of `[controls]` that name the channel.
"""

import asyncio
import logging
import re
from collections.abc import Callable

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.strips import VALUE, CommandStripConfig
from xtouch_daemon.hardware.protocol import RingMode
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv
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


class CommandValue:
    """
    The value of a command channel. A move or a turn changes it at once; `set` runs with the newest value only, as
    programs are slower than hands. Its listeners are called when it changed: by a hand, or by a line of `watch`.
    """

    def __init__(self, config: CommandStripConfig, commands: Commands, encoder_step: int, what: str):
        self.config = config
        self.commands = commands
        self.what = what
        self.low, self.high = config.min, config.max
        self.step = config.step if config.step is not None else (self.high - self.low) * encoder_step / 100
        self.value: float | None = (self.low + self.high) / 2 if commands.simulated else None
        """The value: the one set last, or the one `watch` printed last; None before either."""
        self.touched = False
        """Whether a fader that sets it is under a finger."""
        self.listeners: list[Callable[[], None]] = []
        self._wanted: float | None = None
        """The value to set next, None while there is none."""
        self._setter: asyncio.Task[None] | None = None
        self._watcher = (
            commands.start(self._watch(config.watch), f"{what}: watch") if config.watch is not None else None
        )

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
        return "" if self.value is None else self.config.format.format(value=self.value)

    # -- hands ----------------------------------------------------------------------------------------------------

    def turn(self, steps: int) -> None:
        """Changes the value by `step` per step: from the value, else from `push`, else from `min`."""
        start = self.value if self.value is not None else self.config.push
        self.set((start if start is not None else self.low) + steps * self.step)

    def push(self, pressed: bool) -> None:
        if pressed and self.config.push is not None:
            self.set(self.config.push)

    def moved(self, fraction: float) -> None:
        # in steps of 0.1 % of the range: finer than a hand, and no noise of the fader's resolution in the value
        self.set(self.low + round(fraction, 3) * (self.high - self.low))

    # -- the programs ---------------------------------------------------------------------------------------------

    def set(self, value: float) -> None:
        """Sets the value (between `min` and `max`): at once here, with `set` as soon as the one before is done."""
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
                        self._changed()
                _LOGGER.warning(f"{self.what}: {argv[0]} (watch) ended, again in {WATCH_RESTART:g} s")
            except CommandError as e:
                _LOGGER.warning(f"{self.what}: watch: {e}, again in {WATCH_RESTART:g} s")
            await asyncio.sleep(WATCH_RESTART)

    def close(self) -> None:
        for task in (self._watcher, self._setter):
            if task is not None:
                task.cancel()


class CommandStrip(StripController):
    """
    The strip of a command channel: the fader and the encoder set its value, the LED ring and the second line of the
    LCD show it. The buttons do nothing yet, and there is no meter.
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        look: Look,
        config: CommandStripConfig,
        commands: Commands,
    ):
        super().__init__(strip, env, identity, look)
        self.value = CommandValue(config, commands, env.behavior.encoder_step, identity.name)
        self.value.listeners.append(self.show)

    def update(self, state: AudioState) -> None:
        self.show()

    def show(self) -> None:
        self.strip.set_color(self.color)
        self.strip.set_text(0, self.look.label or self.identity.name)
        self.strip.set_text(1, self.value.text())
        self.strip.set_ring(*self.value.ring())
        self._show_fader()

    def _show_fader(self) -> None:
        if not self.value.touched and (fraction := self.value.fraction()) is not None:
            self.strip.set_fader(fraction)

    # a change of the value shows by its listener (`show()`)

    def on_fader(self, fraction: float) -> None:
        self.value.moved(fraction)

    def on_touch(self, touched: bool) -> None:
        self.value.touched = touched
        # let go, it stays where the hand left it
        self._show_fader()

    def on_encoder(self, steps: int) -> None:
        self.value.turn(steps)

    def on_encoder_press(self, pressed: bool) -> None:
        self.value.push(pressed)

    def close(self) -> None:
        super().close()
        self.value.close()
