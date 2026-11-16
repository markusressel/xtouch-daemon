"""
The strips for sound: devices (`output`, `input`, with profiles or choices), groups of applications (`apps`) and
the next application that plays (`auto`).
"""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from xtouch_daemon.config import presets
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.names import StreamNames, WithPresets
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS, BaseStripConfig
from xtouch_daemon.config.values import LAUNCH_HELP, LAUNCH_WHEN_RUNNING_HELP, Command, Label, Volume


class ProfileConfig(Model):
    """A profile of the sound card of a device strip, e.g. analog or digital output."""

    label: Label
    """The top line of the LCD while the card is in this profile, e.g. "Phones" for the analog output."""
    profile: str
    """
    The name (`output:iec958-stereo+input:analog-stereo`) or description of the profile (`xtouch-daemon list-devices`).
    """
    min_volume: Volume | None = None
    """The volume of the fader at the bottom in this profile; by default the one of the strip."""
    max_volume: Volume | None = None
    """The volume of the fader at the top in this profile (e.g. 200 for weak speakers); by default the strip's."""


class ChoiceConfig(Model):
    """One of the devices a strip switches between with Select, maybe in a profile of its sound card."""

    label: Label | None = None
    """The top line of the LCD while this choice is active; by default the start of the device's description."""
    device: str
    """
    The node name (`xtouch-daemon list-devices`) or description of the device; `*` and `?` are wildcards, e.g.
    `bluez_output.*` for the first Bluetooth headphones there are.
    """
    card: str | None = None
    """
    The sound card whose `profile` the choice needs, by its name (`alsa_card.pci-0000_11_00.4`) or description
    (`xtouch-daemon list-devices`); wildcards allowed.
    """
    profile: str | None = None
    """
    The profile of `card` the device is in, by its name (`output:iec958-stereo+input:analog-stereo`) or
    description. Select switches the card to it first, then the device of the choice becomes the default.
    """
    min_volume: Volume | None = None
    """The volume of the fader at the bottom while this choice is active; by default the one of the strip."""
    max_volume: Volume | None = None
    """The volume of the fader at the top while this choice is active (e.g. 200 for weak speakers)."""

    @field_validator("device")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an empty device name")
        return value

    @model_validator(mode="after")
    def _card_and_profile(self) -> ChoiceConfig:
        if (self.card is None) != (self.profile is None):
            raise ValueError("card and profile go together: the profile of which card")
        return self

    @property
    def title(self) -> str:
        """The label, or else the device: for messages and Home Assistant."""
        return self.label or self.device


class DeviceStripConfig(BaseStripConfig):
    """An output or an input device, or whatever is the default one."""

    type: Annotated[Literal["output", "input"], STRIP_TYPE_MEANINGS]
    device: tuple[str, ...] = ()
    """
    The node name (`xtouch-daemon list-devices`) or description of the device; without it the default device. Several
    (a list, or `*` wildcards like `bluez_output.*`): the strip shows the one of them that is the default, or else the
    one shown last, and Select switches between those that are there.
    """
    label: Label | None = None
    """
    The top line of the LCD; by default "Output" or "Input", or the start of the device's description. The label of
    the active profile (`profiles`) comes first.
    """
    select: bool = True
    """
    Whether the Select button makes the device the default (needs `device` or `choices`); with several devices, a
    press on the default one switches to the next. Its LED is on while the device is the default.
    """
    choices: tuple[ChoiceConfig, ...] = ()
    """
    The devices to switch between with Select, each maybe in a profile of its sound card, e.g. headphones on the
    analog output, speakers on the digital one of the same card, and Bluetooth headphones. Select goes to the next
    one that is there and makes it the default. Instead of `device` and `profiles`.
    """
    profiles: tuple[ProfileConfig, ...] = ()
    """
    Profiles of the device's sound card to switch between with the Rec button, e.g. analog and digital output. Its
    LED is on for every profile but the first. Name `device` so that it matches the devices of every profile (e.g.
    `alsa_output.pci-0000_11_00.4.*`): each profile has a device of its own. `choices` does the same with Select.
    """

    @field_validator("device", mode="before")
    @classmethod
    def _one_or_several(cls, value: object) -> object:
        return (value,) if isinstance(value, str) else value

    @field_validator("device")
    @classmethod
    def _no_blank_device(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not name.strip() for name in value):
            raise ValueError("an empty device name")
        return value

    @field_validator("profiles", "choices")
    @classmethod
    def _two_profiles[T: tuple[ProfileConfig, ...] | tuple[ChoiceConfig, ...]](cls, value: T) -> T:
        if len(value) == 1:
            raise ValueError("at least two to switch between")
        return value

    def volume_ranges(self, behavior: BehaviorConfig) -> list[tuple[str, int, int]]:
        ranges = super().volume_ranges(behavior)
        _, bottom, top = ranges[0]
        for name, options in (("profiles", self.profiles), ("choices", self.choices)):
            for number, option in enumerate(options, start=1):
                ranges.append(
                    (
                        f"{name}[{number}]",
                        bottom if option.min_volume is None else option.min_volume,
                        top if option.max_volume is None else option.max_volume,
                    )
                )
        return ranges

    @model_validator(mode="after")
    def _profiles_take_rec(self) -> DeviceStripConfig:
        if self.profiles and "rec" in self.model_fields_set:
            raise ValueError("rec: with profiles its LED shows the profile")
        return self

    @model_validator(mode="after")
    def _choices_alone(self) -> DeviceStripConfig:
        if not self.choices:
            return self
        if self.device or self.profiles:
            raise ValueError("use either choices or device/profiles")
        if not self.select:
            raise ValueError("select: with choices, Select is how the strip switches between them")
        return self

    @property
    def switches(self) -> bool:
        """Whether Select switches between `choices`."""
        return bool(self.choices)


class AppsStripConfig(BaseStripConfig, WithPresets):
    """All streams of a group of applications, e.g. every browser."""

    type: Annotated[Literal["apps"], STRIP_TYPE_MEANINGS]
    match: Annotated[StreamNames, Field(min_length=1)]
    """
    Parts of the names or binaries of the applications (ignoring case), see `xtouch-daemon list-apps`, e.g. "brave",
    or presets of well-known ones, e.g. `@browsers`, `@voip`, `@games`.
    """
    label: Label
    """The top line of the LCD, e.g. "VoIP"."""
    launch: Command | None = Field(default=None, description=LAUNCH_HELP)
    launch_when_running: bool = Field(default=False, description=LAUNCH_WHEN_RUNNING_HELP)

    @property
    def process_names(self) -> tuple[str, ...]:
        """
        The parts of the names of the processes of the applications, whose processes count as running (`launch`): the
        plain entries of `match`, and the processes of its presets.
        """
        return presets.expand_known(self.written("match"), presets.Kind.PROCESSES)


class AutoStripConfig(BaseStripConfig):
    """The next application that plays and has no strip of its own."""

    type: Annotated[Literal["auto"], STRIP_TYPE_MEANINGS]
    launch: Command | None = Field(default=None, description=LAUNCH_HELP)
    launch_when_running: bool = Field(default=False, description=LAUNCH_WHEN_RUNNING_HELP)
