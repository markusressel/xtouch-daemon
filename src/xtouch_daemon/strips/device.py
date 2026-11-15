"""A strip for an output or an input device, or for the default one."""

from collections.abc import Mapping

from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Device, Direction
from xtouch_daemon.config import Indicator
from xtouch_daemon.protocol import LCD_CELL_WIDTH, Button, Color, Led
from xtouch_daemon.strips.base import Level, StripEnv, VolumeStrip
from xtouch_daemon.surface import Strip


class DeviceStrip(VolumeStrip):
    """
    The volume of a device (`devices` holds its node name or description), or of the default device without
    `devices`, which follows when the default changes. With `select`, the select button makes the device the default,
    and its LED is on while it is. A device that is not there (e.g. headphones that are switched off) shows "off" on a
    dark LCD.

    With several devices (or wildcards, e.g. every pair of Bluetooth headphones) the strip shows one of those that are
    there: the default one, or else the one it showed last (or the first). Select makes it the default; on the default
    one, it switches to the next one and makes that the default.
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
    ):
        default_label = "Output" if direction == Direction.OUTPUT else "Input"
        super().__init__(strip, env, label or default_label, color, meter, indicators)
        self.direction = direction
        self.devices = devices
        self.select = select and bool(devices)
        self.device: Device | None = None
        self.candidates: tuple[Device, ...] = ()
        """The devices of `devices` that are there."""
        self._custom_label = label is not None
        self.default = False
        """Whether the device shown is the default one."""

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
        if self.device is None:
            return None, False
        if not self._custom_label and self.devices:
            self.label = self.device.description[:LCD_CELL_WIDTH]
        return Level(self.device.volume, self.device.muted), True

    def update(self, state: AudioState) -> None:
        super().update(state)
        self.default = self.is_default(state)
        self.strip.set_led(Button.SELECT, Led.ON if self.select and self.default else Led.OFF)

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
        if not (pressed and button == Button.SELECT and self.select and self.device is not None):
            return
        target = self.device
        if self.default and len(self.candidates) > 1:
            # the next one of them
            target = self.candidates[(self.candidates.index(target) + 1) % len(self.candidates)]
        self.run_command(self.env.backend.set_default(self.direction, target.name), "make default")

    async def apply_volume(self, percent: int) -> None:
        if self.device is not None:
            await self.env.backend.set_device_volume(self.direction, self.device.name, percent)

    async def apply_mute(self, muted: bool) -> None:
        if self.device is not None:
            await self.env.backend.set_device_mute(self.direction, self.device.name, muted)
