"""
A strip that belongs to Home Assistant: every part of it is an entity there, and automations decide what it does
(e.g. the fader dims a light, the encoder sets the volume of a media player).

- `number.<ns>_<id>_fader` and `number.<ns>_<id>_encoder`, 0..100: Home Assistant sets them (the motor fader
  moves, the ring shows the encoder), and turning them on the device sets them.
- `text.<ns>_<id>_top` and `text.<ns>_<id>_bottom`: the two lines of the LCD; `select.<ns>_<id>_color`: its color.
- `select.<ns>_<id>_mute_led` (and `select_led`, `rec_led`, `solo_led`): the LEDs of the buttons, off, on or flash.
- `event.<ns>_<id>_buttons`: presses and releases of the buttons and the encoder, touches of the fader.
- `select.<ns>_<id>_output` (`_input`) of an output (input) strip with `choices`: which choice it shows (see
  `ChoiceStrip`).

The buttons don't switch their LEDs: an automation that wants a toggle reacts to the event and sets the LED.

Audio strips can have their fader or their encoder in Home Assistant too (`fader`/`encoder = "homeassistant"`):
`HomeAssistantControls` makes the same `number` entities for them, and an `event` entity for the encoder push and
the touches of the fader.
"""

import asyncio
import dataclasses
from collections.abc import Callable
from typing import get_args

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.event import MQTTEvent
from haad_mqtt_autodiscovery.entity.number import MQTTNumber
from haad_mqtt_autodiscovery.entity.select import MQTTSelect
from haad_mqtt_autodiscovery.entity.text import MQTTText, MQTTTextPayload

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import (
    AppsStripConfig,
    AutoStripConfig,
    ColorName,
    DeviceStripConfig,
    HomeAssistantStripConfig,
    StripConfig,
    color_of,
    default_encoder,
)
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.protocol import LCD_CELL_WIDTH, METER_MAX, RING_MAX, Button, Led, RingMode
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
LEDS = {"off": Led.OFF, "on": Led.ON, "flash": Led.FLASH}
"""The states of an LED in Home Assistant."""


def entity_ids(namespace: str, config: StripConfig, strip_id: str) -> frozenset[str]:
    """
    The unique ids of the entities a strip of the configuration has in Home Assistant (none for most), without making
    them: for the entities of the layouts the device does not show, which stay in Home Assistant.
    """
    if isinstance(config, HomeAssistantStripConfig):
        suffixes = [
            "fader",
            "encoder",
            "meter",
            "top",
            "bottom",
            "color",
            *(f"{button.name.lower()}_led" for button in Button),
            "buttons",
        ]
    elif isinstance(config, DeviceStripConfig | AppsStripConfig | AutoStripConfig):
        encoder = (config.encoder or default_encoder(config.type, config.fader)) == "homeassistant"
        suffixes = [
            *(["fader"] if config.fader == "homeassistant" else []),
            *(["encoder"] if encoder else []),
            *(["buttons"] if config.uses_home_assistant else []),
            # the select of the choices
            *([config.type] if isinstance(config, DeviceStripConfig) and config.switches else []),
        ]
    else:
        suffixes = []
    return frozenset(f"{namespace}_{strip_id}_{suffix}" for suffix in suffixes)


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


class StripEntities:
    """Makes the entities of a strip: ids `<namespace>_<strip_id>_<suffix>`, names `<title> <suffix>`."""

    def __init__(self, bridge: MqttBridge, strip_id: str, title: str):
        self.namespace, self.device = bridge.config.namespace, bridge.device
        self.strip_id = strip_id
        self.title = title

    def number(self, suffix: str) -> MQTTNumber:
        """0..100 %: the fader in tenths, the encoder and the meter in whole steps."""
        return MQTTNumber(
            self.namespace,
            f"{self.strip_id}_{suffix}",
            f"{self.title} {suffix}",
            device=self.device,
            min_val=0,
            max_val=100,
            step=0.1 if suffix == "fader" else 1,
            mode="slider",
            unit_of_measurement="%",
        )

    def events(self, event_types: list[str]) -> MQTTEvent:
        return MQTTEvent(
            self.namespace,
            f"{self.strip_id}_buttons",
            f"{self.title} buttons",
            event_types,
            device_class="button",
            device=self.device,
        )


class FaderLink:
    """
    The motor fader as a number of Home Assistant: Home Assistant moves it, a hand sets it (published at most every
    `FADER_PUBLISH_INTERVAL`), and it stays where the hand let it go.
    """

    def __init__(self, strip: Strip, entity: MQTTNumber):
        self.strip = strip
        self.entity = entity
        self.out = LatestValue(entity, FADER_PUBLISH_INTERVAL)
        self.touched = False
        self._hand: float | None = None

    def show(self) -> None:
        if not self.touched:
            self.strip.set_fader(self.out.value / 100)

    def moved(self, fraction: float) -> None:
        self._hand = round(fraction * 100, 1)
        self.out.set(self._hand)

    def touch(self, touched: bool) -> None:
        self.touched = touched
        if not touched and self._hand is not None:
            # it stays where the hand left it: the motor goes to the target when the fader is let go
            self.strip.set_fader(self._hand / 100)
            self._hand = None

    def close(self) -> None:
        self.out.cancel()


class EncoderLink:
    """The encoder as a number of Home Assistant, 0..100 in steps of `step`, shown on the ring."""

    def __init__(self, strip: Strip, entity: MQTTNumber, step: int):
        self.strip = strip
        self.entity = entity
        self.step = step
        self.out = LatestValue(entity)

    def ring(self) -> tuple[int, RingMode]:
        return _ring(self.out.value), RingMode.WRAP

    def turn(self, steps: int) -> None:
        value = max(0.0, min(100.0, self.out.value + steps * self.step))
        self.out.set(value)
        self.strip.set_ring(_ring(value), RingMode.WRAP)

    def close(self) -> None:
        self.out.cancel()


class HomeAssistantControls:
    """
    The fader and/or the encoder of an audio strip in Home Assistant (`fader`/`encoder = "homeassistant"`), with an
    event entity for the touches of the fader and the push of the encoder. `on_change` is called when Home Assistant
    changes them.
    """

    def __init__(
        self, strip: Strip, env: StripEnv, bridge: MqttBridge, strip_id: str, title: str, fader: bool, encoder: bool
    ):
        self.bridge = bridge
        self.on_change: Callable[[], None] = lambda: None
        entities = StripEntities(bridge, strip_id, title)
        self.fader = FaderLink(strip, entities.number("fader")) if fader else None
        self.encoder = EncoderLink(strip, entities.number("encoder"), env.behavior.encoder_step) if encoder else None
        event_types = [
            *(["fader_touched", "fader_released"] if fader else []),
            *(["encoder_pressed", "encoder_released"] if encoder else []),
        ]
        self.events = entities.events(event_types)
        self.numbers = [link.entity for link in (self.fader, self.encoder) if link is not None]
        self.entities: dict[MQTTEntity, str | None] = {**dict.fromkeys(self.numbers, "0"), self.events: None}
        for entity in self.numbers:
            bridge.watch(entity, lambda _: self.on_change())

    @property
    def connected(self) -> bool:
        """Whether Home Assistant is there and its entities have their states."""
        links = [link for link in (self.fader, self.encoder) if link is not None]
        return self.bridge.ready and None not in [link.out.current for link in links]

    def close(self) -> None:
        for link in (self.fader, self.encoder):
            if link is not None:
                link.close()
        for entity in self.entities:
            self.bridge.unwatch(entity)


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
        entities = StripEntities(bridge, strip_id, label or f"Strip {strip.index + 1}")
        namespace, device, title = entities.namespace, entities.device, entities.title

        def line(suffix: str) -> LcdText:
            return LcdText(namespace, f"{strip_id}_{suffix}", f"{title} {suffix} line", device=device)

        def led(button: Button) -> MQTTSelect:
            name = button.name.lower()
            return MQTTSelect(
                namespace, f"{strip_id}_{name}_led", f"{title} {name} LED", options=list(LEDS), device=device
            )

        self.fader_link = FaderLink(strip, entities.number("fader"))
        self.encoder_link = EncoderLink(strip, entities.number("encoder"), env.behavior.encoder_step)
        self.fader = self.fader_link.entity
        self.encoder = self.encoder_link.entity
        self.meter_level = entities.number("meter")
        self.top = line("top")
        self.bottom = line("bottom")
        self.lcd_color = MQTTSelect(
            namespace, f"{strip_id}_color", f"{title} color", options=list(COLORS), icon="mdi:palette", device=device
        )
        self.leds = {button: led(button) for button in Button}
        self.buttons = entities.events(EVENT_TYPES)
        self._entities: dict[MQTTEntity, str | None] = {
            self.fader: "0",
            self.encoder: "0",
            self.meter_level: "0",
            self.top: self.default_label,
            self.bottom: "",
            self.lcd_color: color,
            **dict.fromkeys(self.leds.values(), "off"),
            self.buttons: None,
        }
        for entity in self._entities:
            if entity is not self.buttons:
                bridge.watch(entity, self._changed)

    @property
    def entities(self) -> dict[MQTTEntity, str | None]:
        """Every entity with the state it starts with in Home Assistant (events have none)."""
        return self._entities

    # -- showing --------------------------------------------------------------------------------------------------

    @property
    def title(self) -> str:
        return self.default_label or super().title

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
        return self.bridge.ready and None not in (self.fader_link.out.current, self.encoder_link.out.current)

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
            self.strip.set_led(button, LEDS.get(led.target_state or "", Led.OFF))
        self.fader_link.show()
        self.strip.set_ring(*self.encoder_link.ring())

    def held_meter(self) -> int | None:
        """
        The level of the meter entity: 0..100 % over the levels of the meter, 100 % lights all LEDs (the red one too),
        nothing while not connected.
        """
        percent = _value(self.meter_level.target_state)
        if not self.connected or percent is None:
            return None
        return round(max(0.0, min(100.0, percent)) / 100 * METER_MAX)

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        if self.connected:
            self.fader_link.moved(fraction)

    def on_touch(self, touched: bool) -> None:
        self.fader_link.touch(touched)
        self._event("fader_touched" if touched else "fader_released")

    def on_encoder(self, steps: int) -> None:
        if self.connected:
            self.encoder_link.turn(steps)

    def on_encoder_press(self, pressed: bool) -> None:
        self._event("encoder_pressed" if pressed else "encoder_released")

    def on_button(self, button: Button, pressed: bool) -> None:
        self._event(f"{button.name.lower()}_{'pressed' if pressed else 'released'}")

    def _event(self, event_type: str) -> None:
        if self.connected:
            self.run_command(self.buttons.trigger(event_type), event_type)

    def close(self) -> None:
        super().close()
        self.fader_link.close()
        self.encoder_link.close()
        for entity in self._entities:
            self.bridge.unwatch(entity)
