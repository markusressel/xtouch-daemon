"""
Custom channels (`type = "custom"`): a strip whose parts do what they are bound to, e.g. a fader that sets the
brightness of a screen with programs of your own. The fader and the encoder of `[controls]` that name the channel set
its values too (it is their `ValueSource`).
"""

from collections.abc import Callable

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.bindings import ValueBinding
from xtouch_daemon.config.strips import CustomStripConfig
from xtouch_daemon.hardware.protocol import RingMode
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv
from xtouch_daemon.strips.value import CommandValue
from xtouch_daemon.system.commands import Commands


class CustomStrip(StripController):
    """
    The strip of a custom channel: a fader and an encoder bound to programs set their values, the LED ring and the
    second line of the LCD show them. An encoder without a binding of its own sets the fader's value in fine steps.
    """

    # bindings: done by the custom strips (Home Assistant, the LCD, color, meter, buttons, targets, present)

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        look: Look,
        config: CustomStripConfig,
        commands: Commands,
    ):
        super().__init__(strip, env, identity, look)
        self.config = config
        self.listeners: list[Callable[[], None]] = []
        """Called when the values are others (`ValueSource`); the target never switches yet."""
        placeholders = {"target": config.targets[0].value} if config.targets else {}
        step = env.behavior.encoder_step

        def value_of(part: object, what: str) -> CommandValue | None:
            if not isinstance(part, ValueBinding):
                return None
            value = CommandValue(part, commands, step, f"{identity.name}.{what}", placeholders)
            value.listeners.append(self.show)
            return value

        self._fader = value_of(config.fader, "fader")
        self._encoder = value_of(config.encoder, "encoder")

    # -- ValueSource ----------------------------------------------------------------------------------------------

    def fader_value(self) -> CommandValue | None:
        return self._fader

    def encoder_value(self) -> CommandValue | None:
        return self._encoder

    @property
    def _knob(self) -> CommandValue | None:
        """What the encoder sets: its own value, else the fader's."""
        return self._encoder or self._fader

    # -- showing --------------------------------------------------------------------------------------------------

    def update(self, state: AudioState) -> None:
        self.show()

    def show(self) -> None:
        self.strip.set_color(self.color)
        self.strip.set_text(0, self.look.label or self.identity.name)
        shown = self._fader or self._encoder
        self.strip.set_text(1, shown.text() if shown is not None else "")
        knob = self._knob
        self.strip.set_ring(*(knob.ring() if knob is not None else (0, RingMode.DOT)))
        self._show_fader()

    def _show_fader(self) -> None:
        if self._fader is None:
            self.strip.set_fader(0.0)
        elif not self._fader.touched and (fraction := self._fader.fraction()) is not None:
            self.strip.set_fader(fraction)

    # -- the device: a change of a value shows by its listener (`show()`) -------------------------------------------

    def on_fader(self, fraction: float) -> None:
        if self._fader is not None:
            self._fader.moved(fraction)

    def on_touch(self, touched: bool) -> None:
        if self._fader is not None:
            self._fader.touched = touched
            # let go, it stays where the hand left it
            self._show_fader()

    def on_encoder(self, steps: int) -> None:
        if self._knob is not None:
            self._knob.turn(steps)

    def on_encoder_press(self, pressed: bool) -> None:
        if self._knob is not None:
            self._knob.push(pressed)

    def close(self) -> None:
        super().close()
        for value in (self._fader, self._encoder):
            if value is not None:
                value.close()
