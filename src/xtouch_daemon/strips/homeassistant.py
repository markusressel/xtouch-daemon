"""
A strip that belongs to Home Assistant: every part of it is an entity there, and automations decide what it does
(e.g. the fader dims a light, the encoder sets the volume of a media player).

- `number.<ns>_<id>_fader` and `number.<ns>_<id>_encoder`, 0..100: Home Assistant sets them (the motor fader
  moves, the ring shows the encoder), and turning them on the device sets them.
- `text.<ns>_<id>_top` and `text.<ns>_<id>_bottom`: the two lines of the LCD; `select.<ns>_<id>_color`: its color.
- `switch.<ns>_<id>_mute_led` (and `select_led`, `rec_led`, `solo_led`): the LEDs of the buttons.
- `event.<ns>_<id>_buttons`: presses and releases of the buttons and the encoder, touches of the fader.

The buttons don't switch their LEDs: an automation that wants a toggle reacts to the event and switches the LED.
"""

import asyncio
import dataclasses
from typing import get_args

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.event import MQTTEvent
from haad_mqtt_autodiscovery.entity.number import MQTTNumber
from haad_mqtt_autodiscovery.entity.select import MQTTSelect
from haad_mqtt_autodiscovery.entity.switch import MQTTSwitch
from haad_mqtt_autodiscovery.entity.text import MQTTText, MQTTTextPayload

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import ColorName, color_of
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.protocol import LCD_CELL_WIDTH, RING_MAX, Button, Led, RingMode
from xtouch_daemon.strips.base import StripController, StripEnv
from xtouch_daemon.surface import Strip

FADER_PUBLISH_INTERVAL = 0.1
"""How often a fader moved by hand publishes its value: Home Assistant and its automations don't need every step."""
OFFLINE_TEXT = "offline"
COLORS: dict[str, ColorName] = {name: name for name in get_args(ColorName)}
EVENT_TYPES = [
    *(f"{button.name.lower()}_{action}" for button in Button for action in ("pressed", "released")),
    "encoder_pressed",
    "encoder_released",
    "fader_touched",
    "fader_released",
]
ON = "ON"


class LcdText(MQTTText):
    """A line of the LCD: Home Assistant lets nobody enter more than fits."""

    def get_discovery_payload(self) -> MQTTTextPayload:
        return dataclasses.replace(super().get_discovery_payload(), max=LCD_CELL_WIDTH)


def _value(text: str | None) -> float | None:
    return None if text is None else float(text)


def _ring(percent: float) -> int:
    return round(percent / 100 * (RING_MAX - 1)) + 1


class LatestValue:
    """
    Publishes the newest value of a number, at most every `interval` seconds: fast moves on the device would
    otherwise flood the broker. `wanted` is the value still to publish.
    """

    def __init__(self, entity: MQTTNumber, interval: float = 0.0):
        self.entity = entity
        self.interval = interval
        self.wanted: float | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def current(self) -> float | None:
        """The value on its way, or else the one of the entity (including what was published but did not come back)."""
        return self.wanted if self.wanted is not None else _value(self.entity.target_state)

    @property
    def value(self) -> float:
        current = self.current
        assert current is not None, "the entity has no state yet"
        return current

    def set(self, value: float) -> None:
        self.wanted = value
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._publish(), name=f"publish {self.entity.entity_id}")

    async def _publish(self) -> None:
        while self.wanted is not None:
            value = self.wanted
            await self.entity.set_state(value)
            if self.wanted == value:
                self.wanted = None
            await asyncio.sleep(self.interval)

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()


class HomeAssistantStrip(StripController):
    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        bridge: MqttBridge,
        strip_id: str,
        label: str | None = None,
        color: ColorName = "white",
    ):
        super().__init__(strip, env, color_of(color), meter=False)
        self.bridge = bridge
        self.default_label = label or ""
        self.default_color: ColorName = color
        self._touched = False
        self._hand: float | None = None
        namespace, device = bridge.config.namespace, bridge.device
        title = label or f"Strip {strip.index + 1}"

        def number(suffix: str) -> MQTTNumber:
            return MQTTNumber(
                namespace,
                f"{strip_id}_{suffix}",
                f"{title} {suffix}",
                device=device,
                min_val=0,
                max_val=100,
                step=0.1 if suffix == "fader" else 1,
                mode="slider",
                unit_of_measurement="%",
            )

        def line(suffix: str) -> LcdText:
            return LcdText(namespace, f"{strip_id}_{suffix}", f"{title} {suffix} line", device=device)

        def led(button: Button) -> MQTTSwitch:
            name = button.name.lower()
            return MQTTSwitch(namespace, f"{strip_id}_{name}_led", f"{title} {name} LED", device=device)

        self.fader = number("fader")
        self.encoder = number("encoder")
        self.top = line("top")
        self.bottom = line("bottom")
        self.lcd_color = MQTTSelect(
            namespace, f"{strip_id}_color", f"{title} color", options=list(COLORS), icon="mdi:palette", device=device
        )
        self.leds = {button: led(button) for button in Button}
        self.buttons = MQTTEvent(
            namespace, f"{strip_id}_buttons", f"{title} buttons", EVENT_TYPES, device_class="button", device=device
        )
        self._fader_out = LatestValue(self.fader, FADER_PUBLISH_INTERVAL)
        self._encoder_out = LatestValue(self.encoder)
        self.entities: dict[MQTTEntity, str | None] = {
            self.fader: "0",
            self.encoder: "0",
            self.top: self.default_label,
            self.bottom: "",
            self.lcd_color: color,
            **dict.fromkeys(self.leds.values(), "OFF"),
            self.buttons: None,
        }
        """Every entity with the state it starts with in Home Assistant (events have none)."""
        for entity in self.entities:
            if entity is not self.buttons:
                bridge.watch(entity, self._changed)

    # -- showing --------------------------------------------------------------------------------------------------

    def update(self, state: AudioState) -> None:
        self.show()

    def _changed(self, entity: MQTTEntity) -> None:
        self.show()

    @property
    def connected(self) -> bool:
        """
        Whether the strip shows what Home Assistant set: connected, and its entities have their states (a new
        configuration has new entities, which the broker gives their states a moment later).
        """
        return self.bridge.ready and None not in (self._fader_out.current, self._encoder_out.current)

    def show(self) -> None:
        if not self.connected:
            # what Home Assistant wants is not known: what the configuration says, and that it is not connected
            self.strip.set_color(self.color)
            self.strip.set_text(0, self.default_label)
            self.strip.set_text(1, OFFLINE_TEXT)
            for button in Button:
                self.strip.set_led(button, Led.OFF)
            return
        self.strip.set_color(color_of(COLORS.get(self.lcd_color.target_state or "", self.default_color)))
        self.strip.set_text(0, self.top.target_state or "")
        self.strip.set_text(1, self.bottom.target_state or "")
        for button, led in self.leds.items():
            self.strip.set_led(button, Led.ON if (led.target_state or "").upper() == ON else Led.OFF)
        if not self._touched:
            self.strip.set_fader(self._fader_out.value / 100)
        self.strip.set_ring(_ring(self._encoder_out.value), RingMode.WRAP)

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        if not self.connected:
            return
        self._hand = round(fraction * 100, 1)
        self._fader_out.set(self._hand)

    def on_touch(self, touched: bool) -> None:
        self._touched = touched
        if not touched and self._hand is not None:
            # it stays where the hand left it: the motor goes to the target when the fader is let go
            self.strip.set_fader(self._hand / 100)
            self._hand = None
        self._event("fader_touched" if touched else "fader_released")

    def on_encoder(self, steps: int) -> None:
        if not self.connected:
            return
        value = max(0.0, min(100.0, self._encoder_out.value + steps * self.env.behavior.encoder_step))
        self._encoder_out.set(value)
        self.strip.set_ring(_ring(value), RingMode.WRAP)

    def on_encoder_press(self, pressed: bool) -> None:
        self._event("encoder_pressed" if pressed else "encoder_released")

    def on_button(self, button: Button, pressed: bool) -> None:
        self._event(f"{button.name.lower()}_{'pressed' if pressed else 'released'}")

    def _event(self, event_type: str) -> None:
        if self.connected:
            self.run_command(self.buttons.trigger(event_type), event_type)

    def close(self) -> None:
        super().close()
        self._fader_out.cancel()
        self._encoder_out.cancel()
        for entity in self.entities:
            self.bridge.unwatch(entity)
