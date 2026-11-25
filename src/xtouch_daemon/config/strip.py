"""
The options strips share: what they show (label, color), their buttons and knobs.
"""

from typing import Annotated

from pydantic import model_validator

from xtouch_daemon.config.base import Meanings, Model
from xtouch_daemon.config.bindings import (
    FADER_PUSH,
    TARGET,
    ColorPart,
    EncoderPart,
    EntityBinding,
    EntityValueBinding,
    FaderPart,
    LcdPart,
    MeterPart,
    ServiceAction,
    ValueBinding,
    entities_in,
    placeholders_of,
    programs_in,
)
from xtouch_daemon.config.buttons import (
    BUTTON_NAMES,
    WHILE_HELD,
    Action,
    ButtonConfig,
    ButtonName,
    ButtonSetup,
    RecButton,
    SelectButton,
    SoloButton,
    default_setup,
    describe_action,
    resolved,
)
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import (
    ENCODERS,
    METER_POINTS,
    MeterPoint,
    Volume,
)

PARTS = ("fader", "encoder", "lcd", "color", "meter")
"""The parts of an audio strip that can be bound, but its buttons."""


class BaseStripConfig(Model):
    color: ColorPart = "white"
    """
    The backlight of the LCD, dark while the strip has nothing to control unless `lit_when_idle` is on. A `watch` sets
    it by color name. An entity sets its own color: a light that is off makes it dark.
    """
    lit_when_idle: bool = False
    """
    Keeps the LCD lit while the strip has nothing to control, e.g. no application plays or the device is not there.
    The fader stays down.
    """
    meter: MeterPart = True
    """
    The LED meter shows the level. Needs `behavior.meters`. A `watch`, a `poll` or an entity makes it show a number,
    from `min` to `max`.
    """
    meter_point: Annotated[MeterPoint, METER_POINTS] | None = None
    """
    Where the meter takes the level: before the volume and Mute of the strip, or after them. By default
    `behavior.meter_point`.
    """
    select: SelectButton = ButtonConfig()
    """
    What Select does (`press`, `hold`) and what its LED shows (`led`). By default it makes the device the default
    (with `device` or `choices`) or starts `launch`, and its LED shows that. `true`/`false` stand for that or nothing.
    """
    rec: RecButton = ButtonConfig()
    """
    What Rec does (`press`, `hold`) and what its LED shows (`led`). By default it switches `profiles`; its LED shows
    the profile, or else a recording. An indicator alone (`rec = "playing"`) sets the LED.
    """
    solo: SoloButton = ButtonConfig()
    """
    What Solo does (`press`, `hold`) and what its LED shows (`led`). By default nothing. An indicator alone (`solo =
    "muted"`) sets the LED.
    """
    min_volume: Volume | None = None
    """The volume, in percent, with the fader at the bottom. E.g. 50 gives the whole fader to the upper half."""
    max_volume: Volume | None = None
    """
    The volume, in percent, with the fader at the top; by default `behavior.max_volume`. Above 100 % the audio is
    amplified, e.g. 200 for weak speakers.
    """
    encoder: EncoderPart | None = None
    """What the encoder does when you turn and push it. Its LED ring shows the value."""
    fader: FaderPart = "volume"
    """What the fader sets. Bound to something else, it gives the volume to the encoder."""
    lcd: LcdPart | None = None
    """
    The second line of the LCD, instead of the volume. A `watch` or a `poll` shows each line it prints, an entity its
    state.
    """

    @property
    def uses_home_assistant(self) -> bool:
        """Whether a part belongs to Home Assistant: it needs `[mqtt]`."""
        parts = (self.fader, self.encoder, self.lcd, self.color, self.meter)
        leds = (self.button(name).led for name in BUTTON_NAMES)
        return "homeassistant" in (*parts, *leds) or bool(self.home_assistant_buttons)

    @property
    def home_assistant_buttons(self) -> tuple[ButtonName, ...]:
        """The buttons that belong to Home Assistant (`press = "homeassistant"`)."""
        return tuple(name for name in BUTTON_NAMES if self.button(name).press == "homeassistant")

    def button(self, name: ButtonName) -> ButtonSetup:
        """What a button does: its table, the rest as the strip type does it (see `buttons.default_setup`)."""
        default = default_setup(
            name,
            str(getattr(self, "type", "")),
            devices=bool(getattr(self, "device", ()) or getattr(self, "choices", ())),
            profiles=bool(getattr(self, "profiles", ())),
            launch=getattr(self, "launch", None) is not None,
        )
        return resolved(getattr(self, name), default)

    @model_validator(mode="after")
    def _buttons_can(self) -> BaseStripConfig:
        """Each action of a button needs what it acts on: devices, profiles, a program, an input."""
        for name in BUTTON_NAMES:
            setup = self.button(name)
            for part, action in (("press", setup.press), ("hold", setup.hold)):
                if (problem := self._cannot(action)) is not None:
                    raise ValueError(f"{name}.{part}: {describe_action(action)} {problem}")
            if setup.press in WHILE_HELD and setup.hold != "off":
                raise ValueError(f"{name}.hold: {setup.press} lasts while the button is held, it takes no hold")
            if setup.hold == "homeassistant":
                raise ValueError(f'{name}.hold: "homeassistant" takes the whole button: set it as press')
        return self

    def _cannot(self, action: Action) -> str | None:
        """Why the strip can't do the action, None if it can."""
        strip_type = str(getattr(self, "type", ""))
        devices = bool(getattr(self, "device", ()) or getattr(self, "choices", ()))
        match action:
            case "default" | "next" if strip_type not in ("output", "input"):
                return "is for output and input strips"
            case "default" | "next" if not devices:
                return "needs device or choices"
            case "profile" if not getattr(self, "profiles", ()):
                return "needs profiles"
            case "launch" if getattr(self, "launch", None) is None:
                return "needs launch"
            case "talk" if strip_type != "input":
                return "is for input strips"
            case _:
                return None

    @model_validator(mode="after")
    def _encoder_of_the_type(self) -> BaseStripConfig:
        strip_type = str(getattr(self, "type", ""))
        if isinstance(self.encoder, str) and self.encoder not in ENCODERS[strip_type]:
            raise ValueError(
                f"encoder: {self.encoder} is not for {strip_type} strips ({', '.join(ENCODERS[strip_type])})"
            )
        if self.fader != "volume" and self.encoder not in (None, "volume"):
            where = (
                "in Home Assistant"
                if self.fader == "homeassistant"
                else "bound to an entity"
                if isinstance(self.fader, EntityValueBinding)
                else "bound to a program"
            )
            raise ValueError(f"encoder: with the fader {where}, the encoder sets the volume")
        if isinstance(self.fader, ValueBinding | EntityValueBinding) and self.fader.push is not None:
            raise ValueError(FADER_PUSH)
        if getattr(self, "launch_when_running", False) and getattr(self, "launch", None) is None:
            raise ValueError("launch_when_running: needs launch")
        return self

    @model_validator(mode="after")
    def _no_targets(self) -> BaseStripConfig:
        """Only the programs of `custom` channels have targets."""
        for where, argv in self.programs().items():
            if "target" in placeholders_of(argv):
                raise ValueError(f"{where}: {TARGET} is for custom channels with targets")
        return self

    def programs(self) -> dict[str, tuple[str, ...]]:
        """The programs of its parts, by where they are, e.g. `fader.set`, `select.press.run`."""
        return programs_in(self, PARTS, BUTTON_NAMES)

    def entities(self) -> dict[str, EntityBinding | ServiceAction]:
        """Its parts and actions with entities of Home Assistant, by where they are, e.g. `meter`, `select.press`."""
        return entities_in(self, PARTS, BUTTON_NAMES)

    def volume_ranges(self, behavior: BehaviorConfig) -> list[tuple[str, int, int]]:
        """Where each volume range of the strip is configured (e.g. `profiles[2]`, "" for the strip), and the range."""
        bottom = 0 if self.min_volume is None else self.min_volume
        top = behavior.max_volume if self.max_volume is None else self.max_volume
        return [("", bottom, top)]


STRIP_TYPE_MEANINGS = Meanings(
    {
        "output": "An output device (speakers, headphones): the fader sets its volume. One device, one of several, or "
        "whatever is the default output.",
        "input": "An input device (a microphone): the fader sets its volume. One device, one of several, or whatever "
        "is the default input.",
        "apps": "All playback streams of a group of applications, e.g. every browser, like the per-application "
        "sliders of pavucontrol.",
        "auto": "The next application that plays and has no channel of its own, and the people of the voice chat.",
        "homeassistant": "A strip for Home Assistant: its fader, encoder, LCD, LEDs and buttons are entities there, "
        "and automations decide what they do. Needs `[mqtt]`.",
        "custom": "A strip of your own: each part does what you bind it to, in Home Assistant or with programs of "
        "your own. E.g. the fader sets the brightness of a screen.",
        "empty": "A dark strip that does nothing; its fader stays at the bottom.",
        "voip": "A participant of the voice chat: the fader sets their volume, Mute mutes them for you, the meter "
        "shows their voice. With `person` always the same one, else one of the people `auto` hands out.",
    }
)
"""What each strip type is, shown when it is chosen."""
