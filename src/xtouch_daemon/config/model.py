"""
The whole configuration: the sections of the daemon and the device, and the channels, states and slots.
"""

from typing import TYPE_CHECKING

from pydantic import PrivateAttr

from xtouch_daemon.config.base import Model
from xtouch_daemon.config.layout_strips import VoipStripConfig
from xtouch_daemon.config.sections import BehaviorConfig, DeviceConfig, MqttConfig, SwitchingConfig, VoipConfig
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import StripConfig
from xtouch_daemon.config.values import Label, MeterPoint

if TYPE_CHECKING:
    from xtouch_daemon.config.slots import SlotsSetup


class Config(Model):
    device: DeviceConfig = DeviceConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    aliases: dict[str, Label] = {}  # noqa: RUF012 - a pydantic model, which copies the default
    """
    Names to show on `auto` strips for applications, at most 7 characters: for the name the sound server reports
    (`xtouch-daemon list-apps`), the label, e.g. "Discord" for "WEBRTC VoiceEngine".
    """
    mqtt: MqttConfig | None = None
    """The MQTT broker, needed by `homeassistant` channels and controls."""
    switching: SwitchingConfig = SwitchingConfig()
    voip: VoipConfig | None = None
    """The participants of the voice chat, who share the `auto` slots: without the section, its defaults (`bridge`)."""
    _slots: SlotsSetup | None = PrivateAttr(default=None)

    @property
    def slots(self) -> SlotsSetup:
        """The channels, states and slots (see `config.slots.setup()`, which every file goes through)."""
        assert self._slots is not None, "parse_config() sets up the slots"
        return self._slots

    def meter_point(self, strip: StripConfig) -> MeterPoint:
        """Where the meter of a strip takes the level: its own `meter_point`, else `behavior.meter_point`."""
        if isinstance(strip, BaseStripConfig | VoipStripConfig) and strip.meter_point is not None:
            return strip.meter_point
        return self.behavior.meter_point
