"""
The strips for sound: devices (`output`, `input`, with profiles or choices), groups of applications (`apps`) and
the next application that plays (`auto`).
"""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from xtouch_daemon.config import presets
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.buttons import BUTTON_NAMES
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
    The profile, by its name (`output:iec958-stereo+input:analog-stereo`) or description. `xtouch-daemon
    list-devices` lists them.
    """
    min_volume: Volume | None = None
    """The volume, in percent, with the fader at the bottom in this profile; by default that of the strip."""
    max_volume: Volume | None = None
    """
    The volume, in percent, with the fader at the top in this profile; by default that of the strip. E.g. 200 for
    weak speakers.
    """


class ChoiceConfig(Model):
    """One of the devices a strip switches between with Select, maybe in a profile of its sound card."""

    label: Label | None = None
    """The top line of the LCD while this choice is active; by default the start of the description of the device."""
    device: str
    """
    The device, by its node name or description (`xtouch-daemon list-devices`). `*` and `?` are wildcards, e.g.
    `bluez_output.*` for the first Bluetooth headphones there are.
    """
    card: str | None = None
    """
    The sound card whose `profile` the choice needs, by its name (`alsa_card.pci-0000_11_00.4`) or description.
    Wildcards work.
    """
    profile: str | None = None
    """
    The profile of `card` for this choice, by its name or description. Select switches the card to it first, then
    makes the device the default.
    """
    min_volume: Volume | None = None
    """
    The volume, in percent, with the fader at the bottom while this choice is active; by default that of the strip.
    """
    max_volume: Volume | None = None
    """
    The volume, in percent, with the fader at the top while this choice is active; by default that of the strip.
    E.g. 200 for weak speakers.
    """

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
    The device, by its node name or description (`xtouch-daemon list-devices`); without it, the default device. With
    several (a list, or wildcards like `bluez_output.*`), the strip shows the default one of them, and Select
    switches between them.
    """
    label: Label | None = None
    """
    The top line of the LCD; by default "Output", "Input" or the start of the description of the device. The label
    of the active profile comes first.
    """
    choices: tuple[ChoiceConfig, ...] = ()
    """
    The devices Select switches between, each maybe in a profile of its sound card. E.g. headphones on the analog
    output, speakers on the digital one, Bluetooth headphones. Instead of `device` and `profiles`.
    """
    profiles: tuple[ProfileConfig, ...] = ()
    """
    Profiles of the sound card that Rec switches between, e.g. analog and digital output. Its LED is lit for every
    profile but the first. `device` must match the device of every profile, e.g. `alsa_output.pci-0000_11_00.4.*`.
    """

    @field_validator("device", mode="before", json_schema_input_type=str | list[str])
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
    def _choices_alone(self) -> DeviceStripConfig:
        if not self.choices:
            return self
        if self.device or self.profiles:
            raise ValueError("use either choices or device/profiles")
        actions = [action for name in BUTTON_NAMES for action in (self.button(name).press, self.button(name).hold)]
        if not any(action in ("default", "next") for action in actions):
            raise ValueError("choices: no button switches between them (`default` or `next`, Select by default)")
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
    The applications, by a part of their name or program (any case), e.g. "brave", or presets like `@browsers`,
    `@voip`, `@games`. `xtouch-daemon list-apps` lists them.
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
