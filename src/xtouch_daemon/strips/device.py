"""A strip for an output or an input device, or for the default one."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Card, Device, Direction
from xtouch_daemon.config import EncoderMode, Indicator, ProfileConfig
from xtouch_daemon.protocol import LCD_CELL_WIDTH, Button, Color, Led
from xtouch_daemon.strips.base import Level, StripEnv, VolumeStrip
from xtouch_daemon.surface import Strip

if TYPE_CHECKING:
    from xtouch_daemon.strips.homeassistant import HomeAssistantControls

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Switch:
    """A switch of the sound card to a profile, until the card is in it."""

    card: str
    profile: str
    """The name of the profile."""
    config: ProfileConfig
    make_default: bool
    """Whether the device of the profile becomes the default (the old one was)."""


class DeviceStrip(VolumeStrip):
    """
    The volume of a device (`devices` holds its node name or description), or of the default device without
    `devices`, which follows when the default changes. With `select`, the select button makes the device the default,
    and its LED is on while it is. A device that is not there (e.g. headphones that are switched off) shows "off" on a
    dark LCD.

    With several devices (or wildcards, e.g. every pair of Bluetooth headphones) the strip shows one of those that are
    there: the default one, or else the one it showed last (or the first). Select makes it the default; on the default
    one, it switches to the next one and makes that the default.

    With `profiles`, the rec button switches the sound card of the device to the next of them (e.g. from analog to
    digital output), and its LED is on for every profile but the first. The label of the profile is the label of the
    strip (e.g. "Phones" for the analog output, "Speaker" for the digital one), from the press on. The devices of the
    card change with it: if the old one was the default, the new one becomes the default. A profile may have a volume
    range of its own (e.g. up to 200 % for weak speakers).
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        direction: Direction,
        devices: tuple[str, ...],
        label: str | None = None,
        color: Color = Color.WHITE,
        meter: bool = True,
        select: bool = True,
        indicators: Mapping[Button, Indicator] | None = None,
        profiles: tuple[ProfileConfig, ...] = (),
        min_volume: int | None = None,
        max_volume: int | None = None,
        encoder: EncoderMode = "volume",
        controls: HomeAssistantControls | None = None,
    ):
        default_label = "Output" if direction == Direction.OUTPUT else "Input"
        super().__init__(
            strip, env, label or default_label, color, meter, indicators, min_volume, max_volume, encoder, controls
        )
        self.direction = direction
        self.devices = devices
        self.select = select and bool(devices)
        self.device: Device | None = None
        self.candidates: tuple[Device, ...] = ()
        """The devices of `devices` that are there."""
        self._label_option = label
        self.default = False
        """Whether the device shown is the default one."""
        self.profiles = profiles
        if profiles:
            # its LED shows the profile
            self.indicators.pop(Button.REC, None)
        self.card: Card | None = None
        """The sound card of the device shown."""
        self._switch: _Switch | None = None

    def _shown(self, state: AudioState) -> Device | None:
        if not self.devices:
            return state.device(self.direction, None)
        candidates = state.devices_matching(self.direction, self.devices)
        default = next((device for device in candidates if state.is_default(device)), None)
        last = next((device for device in candidates if self.device and device.name == self.device.name), None)
        return default or last or next(iter(candidates), None)

    def current(self, state: AudioState) -> tuple[Level | None, bool]:
        self.device = self._shown(state)
        self.candidates = state.devices_matching(self.direction, self.devices)
        self.card = state.card(self.device.card) if self.device is not None else None
        self._update_label()
        if self.device is None:
            return None, False
        return Level(self.device.volume, self.device.muted, self.device.balance), True

    def update(self, state: AudioState) -> None:
        super().update(state)
        self.default = self.is_default(state)
        self.strip.set_led(Button.SELECT, Led.ON if self.select and self.default else Led.OFF)
        if self.profiles:
            self.strip.set_led(Button.REC, Led.ON if self.profile_index() not in (None, 0) else Led.OFF)
        switch = self._switch
        # the device of the profile switched to is there
        if self.card is not None and self.device is not None and switch is not None:
            if (self.card.name, self.card.profile) != (switch.card, switch.profile):
                return
            self._switch = None
            if switch.make_default and not self.default:
                self.run_command(self.env.backend.set_default(self.direction, self.device.name), "make default")

    def _update_label(self) -> None:
        """The label of the profile, else the configured one, else the start of the description of the device."""
        if (profile := self._profile()) is not None:
            self.label = profile.label
        elif self._label_option is not None:
            self.label = self._label_option
        elif self.devices and self.device is not None:
            self.label = self.device.description[:LCD_CELL_WIDTH]

    def volume_range(self) -> tuple[int, int]:
        bottom, top = super().volume_range()
        if (profile := self._profile()) is None:
            return bottom, top
        return (
            bottom if profile.min_volume is None else profile.min_volume,
            top if profile.max_volume is None else profile.max_volume,
        )

    def _profile(self) -> ProfileConfig | None:
        """The profile the card is in (or switches to), None for another one."""
        if self._switch is not None:
            return self._switch.config
        index = self.profile_index()
        return None if index is None else self.profiles[index]

    def profile_index(self) -> int | None:
        """Which of `profiles` the card of the device is in, None for another one (or without a card)."""
        if self.card is None:
            return None
        active = self.card.profile_named(self.card.profile)
        return next(
            (i for i, profile in enumerate(self.profiles) if active is not None and active.matches(profile.profile)),
            None,
        )

    def recording(self, state: AudioState) -> bool:
        return self.device is not None and state.is_recorded(self.device)

    def playing(self, state: AudioState) -> bool:
        return self.device is not None and self.device.running

    def is_default(self, state: AudioState) -> bool:
        return self.device is not None and state.is_default(self.device)

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        device = self._shown(state)
        if not self.meter or device is None:
            return set()
        return {CaptureTarget(device.name, monitor=self.direction == Direction.OUTPUT)}

    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool:
        device = state.device(self.direction, target.node)
        return device is not None and device.running

    def on_button(self, button: Button, pressed: bool) -> None:
        super().on_button(button, pressed)
        if pressed and button == Button.REC and self.profiles:
            self._switch_profile()
        if not (pressed and button == Button.SELECT and self.select and self.device is not None):
            return
        target = self.device
        if self.default and len(self.candidates) > 1:
            # the next one of them
            target = self.candidates[(self.candidates.index(target) + 1) % len(self.candidates)]
        self.run_command(self.env.backend.set_default(self.direction, target.name), "make default")

    def _switch_profile(self) -> None:
        card = self.card
        if card is None:
            return
        index = self.profile_index()
        wanted = self.profiles[0 if index is None else (index + 1) % len(self.profiles)]
        profile = card.profile_named(wanted.profile)
        if profile is None:
            _LOGGER.warning(f"Strip {self.strip.index + 1}: {card.name} has no profile {wanted.profile!r}")
            return
        self._switch = _Switch(card.name, profile.name, wanted, make_default=self.default)
        self.label = wanted.label
        self.show()
        self.run_command(self._set_profile(self._switch), f"switch to {wanted.label}")

    async def _set_profile(self, switch: _Switch) -> None:
        try:
            await self.env.backend.set_card_profile(switch.card, switch.profile)
        except AudioCommandError:
            if self._switch is switch:
                self._switch = None
                # back to the label of the profile the card is still in
                self._update_label()
                self.show()
            raise

    async def apply_volume(self, percent: int) -> None:
        if self.device is not None:
            await self.env.backend.set_device_volume(self.direction, self.device.name, percent)

    async def apply_mute(self, muted: bool) -> None:
        if self.device is not None:
            await self.env.backend.set_device_mute(self.direction, self.device.name, muted)

    async def apply_balance(self, balance: float) -> None:
        if self.device is not None:
            await self.env.backend.set_device_balance(self.direction, self.device.name, balance)
