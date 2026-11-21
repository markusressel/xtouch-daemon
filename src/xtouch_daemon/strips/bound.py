"""
The parts of a strip bound to programs of your own (`config.bindings`), as a controller runs them: the values of a
fader and an encoder (`CommandValue`) and the lines of the watches of the LCD, the color, the meter and the LEDs
(`WatchedLine`). `BoundParts` keeps them for as long as the controller lives; another look keeps those that stay the
same, so a watch does not start again when a strip moves to another place.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from xtouch_daemon.config.bindings import HomeAssistant, LevelBinding, ValueBinding, WatchBinding
from xtouch_daemon.config.buttons import ButtonSetup
from xtouch_daemon.config.values import ColorName
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.strips.value import CommandValue, WatchedLine, color_of_line
from xtouch_daemon.system.commands import Commands


@dataclass(frozen=True)
class Parts:
    """
    The parts of a look that do something else than the strip type: bound to a program of your own, or to Home
    Assistant (`"homeassistant"`). None for what the type does. A fader or an encoder in Home Assistant is not here:
    `HomeAssistantControls` has it for as long as the controller.
    """

    fader: ValueBinding | None = None
    encoder: ValueBinding | None = None
    lcd: HomeAssistant | WatchBinding | None = None
    """The second line of the LCD."""
    color: HomeAssistant | WatchBinding | None = None
    """The backlight of the LCD; the look's color is what it shows until it is known."""
    meter: HomeAssistant | LevelBinding | None = None


def led_key(button: Button) -> str:
    """The key of the watch of the LED of a button in `BoundParts.lines`, e.g. `select.led`."""
    return f"{button.name.lower()}.led"


class BoundParts:
    """
    The programs of the bound parts of a controller: its values and watches. `on_change` is called when one of them
    changed (a value, a line). `what` names them in the log, e.g. `Speakers`.
    """

    def __init__(self, commands: Commands, encoder_step: int, what: str, on_change: Callable[[], None]):
        self.commands = commands
        self.encoder_step = encoder_step
        self.what = what
        self.on_change = on_change
        self.fader: CommandValue | None = None
        """The value the fader sets, None for a fader that is not bound to a program."""
        self.encoder: CommandValue | None = None
        """The value the encoder sets, None for an encoder that is not bound to a program."""
        self.lines: dict[str, WatchedLine] = {}
        """The watches of the parts: `lcd`, `color`, `meter`, and `select.led` ... (see `led_key()`)."""
        self.color: ColorName | None = None
        """The color the watch of the color named last; None before it named one."""

    def bind(self, parts: Parts, buttons: Mapping[Button, ButtonSetup]) -> None:
        """
        Runs the programs of `parts` and of the LEDs of `buttons`: those that are the same as before go on, the
        others end.
        """
        self.fader = self._value(self.fader, parts.fader, "fader")
        self.encoder = self._value(self.encoder, parts.encoder, "encoder")
        watches = {"lcd": parts.lcd, "color": parts.color, "meter": parts.meter}
        watches |= {led_key(button): setup.led for button, setup in buttons.items()}
        wanted = {key: part.watch for key, part in watches.items() if isinstance(part, WatchBinding)}
        for key in [key for key, line in self.lines.items() if wanted.get(key) != line.argv]:
            self.lines.pop(key).close()
            if key == "color":
                self.color = None
        for key, argv in wanted.items():
            if key not in self.lines:
                line = WatchedLine(argv, self.commands, f"{self.what}.{key}")
                line.listeners.append(self._color_printed if key == "color" else self.on_change)
                self.lines[key] = line

    def _value(self, value: CommandValue | None, binding: ValueBinding | None, what: str) -> CommandValue | None:
        if value is not None and value.binding == binding:
            return value
        if value is not None:
            value.close()
        if binding is None:
            return None
        value = CommandValue(binding, self.commands, self.encoder_step, f"{self.what}.{what}")
        value.listeners.append(self.on_change)
        return value

    def _color_printed(self) -> None:
        # a line that is no color keeps the color
        if (color := color_of_line(self.line("color") or "")) is not None and color != self.color:
            self.color = color
            self.on_change()

    def line(self, key: str) -> str | None:
        """The newest line of the watch of a part (`lcd`, `select.led`, ...); None before the first, or without it."""
        watched = self.lines.get(key)
        return watched.line if watched is not None else None

    def close(self) -> None:
        for value in (self.fader, self.encoder):
            if value is not None:
                value.close()
        for line in self.lines.values():
            line.close()
        self.fader = self.encoder = None
        self.lines.clear()
