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

Audio strips can have parts in Home Assistant too (`fader`, `encoder`, `lcd`, `color`, `meter`, the `led` of a button
= "homeassistant"): `HomeAssistantControls` makes the same entities for them, and an `event` entity for the encoder
push, the touches of the fader and the presses of buttons. A fader or an encoder bound to a program of your own is a
`number` there too, from the `min` to the `max` of its binding: a change there sets the value (`ValueLink`).
"""

import asyncio
import dataclasses
import math
from collections.abc import Callable, Mapping
from typing import get_args

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.event import MQTTEvent
from haad_mqtt_autodiscovery.entity.number import MQTTNumber
from haad_mqtt_autodiscovery.entity.select import MQTTSelect
from haad_mqtt_autodiscovery.entity.text import MQTTText, MQTTTextPayload

from xtouch_daemon.audio.meter import Lit
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.bindings import ValueBinding
from xtouch_daemon.config.values import ColorName, MeterPoint, color_of
from xtouch_daemon.hardware.protocol import LCD_CELL_WIDTH, METER_MAX, RING_MAX, Button, Led, RingMode
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.strips.base import OFFLINE_TEXT, Identity, Look, StripController, StripEnv
from xtouch_daemon.strips.value import CommandValue

FADER_PUBLISH_INTERVAL = 0.1
"""How often a fader moved by hand publishes its value: Home Assistant and its automations don't need every step."""
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
    """Makes the entities of a controller: ids `<namespace>_<id>_<suffix>`, names `<name> <suffix>` (its identity)."""

    def __init__(self, bridge: MqttBridge, identity: Identity):
        self.namespace, self.device = bridge.config.namespace, bridge.device
        self.strip_id = identity.id
        self.title = identity.name

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

    def value_number(self, suffix: str, binding: ValueBinding, step: float) -> MQTTNumber:
        """A value of programs of your own (`fader`, `encoder`): from its `min` to its `max`, in steps of `step`."""
        return MQTTNumber(
            self.namespace,
            f"{self.strip_id}_{suffix}",
            f"{self.title} {suffix}",
            device=self.device,
            min_val=binding.min,
            max_val=binding.max,
            step=step,
            mode="slider",
        )

    def line(self, suffix: str) -> LcdText:
        """A line of the LCD (`top`, `bottom`)."""
        return LcdText(self.namespace, f"{self.strip_id}_{suffix}", f"{self.title} {suffix} line", device=self.device)

    def color(self) -> MQTTSelect:
        """The color of the LCD."""
        return MQTTSelect(
            self.namespace,
            f"{self.strip_id}_color",
            f"{self.title} color",
            options=list(COLORS),
            icon="mdi:palette",
            device=self.device,
        )

    def led(self, name: str) -> MQTTSelect:
        """The LED of a button (`select`, `mute`, ...)."""
        return MQTTSelect(
            self.namespace,
            f"{self.strip_id}_{name}_led",
            f"{self.title} {name} LED",
            options=list(LEDS),
            device=self.device,
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


class ValueLink:
    """
    A value of programs of your own as a number of Home Assistant (`number.<ns>_<id>_fader`, `_encoder`): a change
    there sets the value (it runs `set`, as a move does), and the number follows the value. `attach()` gives it the
    value of the controller.
    """

    def __init__(self, bridge: MqttBridge, entity: MQTTNumber):
        self.bridge = bridge
        self.entity = entity
        self.out = LatestValue(entity, FADER_PUBLISH_INTERVAL)
        self.value: CommandValue | None = None
        bridge.watch_commands(entity, self._commanded)

    def attach(self, value: CommandValue | None) -> None:
        if value is self.value:
            return
        if self.value is not None:
            self.value.listeners.remove(self.publish)
        self.value = value
        if value is not None:
            value.listeners.append(self.publish)
            self.publish()

    def publish(self) -> None:
        """Home Assistant shows the value: a state that says otherwise is put right."""
        value = self.value.value if self.value is not None else None
        if value is not None and self.bridge.ready and self.out.current != value:
            self.out.set(value)

    def _commanded(self, payload: str) -> None:
        try:
            wanted = float(payload)
        except ValueError:
            return
        if self.value is not None:
            self.value.set(wanted)

    def close(self) -> None:
        self.attach(None)
        self.out.cancel()


class HomeAssistantControls:
    """
    The parts of an audio strip in Home Assistant: the fader and/or the encoder (`fader`/`encoder = "homeassistant"`),
    the second line of the LCD (`lcd`), its color (`color`), the meter (`meter`) and the LEDs of `leds`, with an event
    entity for the touches of the fader, the push of the encoder and the presses of `buttons` (those with `press =
    "homeassistant"`). A fader or an encoder bound to a program (`values`) is a number there too. `on_change` is called
    when Home Assistant changes them.
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        bridge: MqttBridge,
        identity: Identity,
        fader: bool,
        encoder: bool,
        buttons: tuple[str, ...] = (),
        *,
        lcd: bool = False,
        color: bool = False,
        meter: bool = False,
        leds: tuple[str, ...] = (),
        values: Mapping[str, ValueBinding] | None = None,
    ):
        self.bridge = bridge
        self.on_change: Callable[[], None] = lambda: None
        entities = StripEntities(bridge, identity)
        self.fader = FaderLink(strip, entities.number("fader")) if fader else None
        self.encoder = EncoderLink(strip, entities.number("encoder"), env.behavior.encoder_step) if encoder else None
        event_types = [
            *(["fader_touched", "fader_released"] if fader else []),
            *(["encoder_pressed", "encoder_released"] if encoder else []),
            *(f"{button}_{action}" for button in buttons for action in ("pressed", "released")),
        ]
        self.events = entities.events(event_types) if event_types else None
        """The events of the device, None without any."""
        self.bottom = entities.line("bottom") if lcd else None
        self.color = entities.color() if color else None
        self.meter = entities.number("meter") if meter else None
        self.leds = {name: entities.led(name) for name in leds}
        """The LEDs of the buttons, by name (`select`)."""
        self.values = {
            name: ValueLink(bridge, entities.value_number(name, binding, _value_step(name, binding, env)))
            for name, binding in (values or {}).items()
        }
        """The values of programs of your own, by part (`fader`, `encoder`)."""
        self.numbers = [link.entity for link in (self.fader, self.encoder) if link is not None]
        self.entities: dict[MQTTEntity, str | None] = {
            **dict.fromkeys(self.numbers, "0"),
            **({self.bottom: ""} if self.bottom is not None else {}),
            **({self.color: "white"} if self.color is not None else {}),
            **({self.meter: "0"} if self.meter is not None else {}),
            **dict.fromkeys(self.leds.values(), "off"),
            # the value is the programs': the number gets it once it is known
            **dict.fromkeys((link.entity for link in self.values.values()), None),
            **({self.events: None} if self.events is not None else {}),
        }
        for entity in self.entities:
            if entity is not self.events:
                bridge.watch(entity, lambda _: self._changed())

    def _changed(self) -> None:
        for link in self.values.values():
            link.publish()
        self.on_change()

    @property
    def connected(self) -> bool:
        """Whether Home Assistant is there and its entities have their states."""
        links = [link for link in (self.fader, self.encoder) if link is not None]
        return self.bridge.ready and None not in [link.out.current for link in links]

    def attach(self, fader: CommandValue | None, encoder: CommandValue | None) -> None:
        """The values of the fader and the encoder bound to programs, for their numbers."""
        for name, value in (("fader", fader), ("encoder", encoder)):
            if (link := self.values.get(name)) is not None:
                link.attach(value)

    def bottom_text(self) -> str:
        """The second line of the LCD as Home Assistant sets it; `offline` while it is not there."""
        if self.bottom is None or not self.connected:
            return OFFLINE_TEXT
        return self.bottom.target_state or ""

    def color_name(self, default: ColorName) -> ColorName:
        """The color of the LCD as Home Assistant sets it; `default` while it is not there, or for no color."""
        if self.color is None or not self.connected:
            return default
        return COLORS.get(self.color.target_state or "", default)

    def meter_level(self) -> Lit | None:
        """The level of the meter, 0..100 % over its LEDs; None while Home Assistant is not there."""
        return _lit(self.meter.target_state) if self.meter is not None and self.connected else None

    def led(self, name: str) -> Led:
        """The LED of a button as Home Assistant sets it; off while it is not there."""
        entity = self.leds.get(name)
        if entity is None or not self.connected:
            return Led.OFF
        return LEDS.get(entity.target_state or "", Led.OFF)

    def close(self) -> None:
        for link in (self.fader, self.encoder, *self.values.values()):
            if link is not None:
                link.close()
        for entity in self.entities:
            self.bridge.unwatch(entity)


def _value_step(name: str, binding: ValueBinding, env: StripEnv) -> float:
    """
    The step of the number of a value: an encoder's step (as `CommandValue` computes it), a fader's 0.1 % of the range
    as a power of ten (0.1 for 0..100, 0.001 for 0.1..1), so the slider of Home Assistant sends round values.
    """
    span = binding.max - binding.min
    if name == "encoder":
        # rounded off: 0.9 * 5 / 100 is 0.045000000000000005
        return binding.step if binding.step is not None else round(span * env.behavior.encoder_step / 100, 9)
    return 10.0 ** round(math.log10(span / 1000))


def _lit(text: str | None) -> Lit | None:
    """A level of 0..100 % over the LEDs of the meter: 100 % lights all of them, the red one too."""
    percent = _value(text)
    return None if percent is None else Lit(round(max(0.0, min(100.0, percent)) / 100 * METER_MAX))


class OfflineHomeAssistantStrip(StripController):
    """
    A `homeassistant` strip without MQTT (Simulate has none): it looks as while Home Assistant is not there, and the
    hands do nothing.
    """

    def update(self, state: AudioState) -> None:
        self.strip.set_color(self.color)
        self.strip.set_text(0, self.look.label or "")
        self.strip.set_text(1, OFFLINE_TEXT)
        for button in Button:
            self.strip.set_led(button, Led.OFF)
        self.strip.set_ring(0, RingMode.DOT)


class HomeAssistantStrip(StripController):
    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        bridge: MqttBridge,
        identity: Identity,
        look: Look,
    ):
        """Home Assistant sets the meter (`held_meter()`): the look's `meter` means nothing here."""
        super().__init__(strip, env, identity, look)
        self.bridge = bridge
        self.default_label = look.label or ""
        self.default_color: ColorName = look.color
        entities = StripEntities(bridge, identity)

        self.fader_link = FaderLink(strip, entities.number("fader"))
        self.encoder_link = EncoderLink(strip, entities.number("encoder"), env.behavior.encoder_step)
        self.fader = self.fader_link.entity
        self.encoder = self.encoder_link.entity
        self.meter_level = entities.number("meter")
        self.top = entities.line("top")
        self.bottom = entities.line("bottom")
        self.lcd_color = entities.color()
        self.leds = {button: entities.led(button.name.lower()) for button in Button}
        self.buttons = entities.events(EVENT_TYPES)
        self._entities: dict[MQTTEntity, str | None] = {
            self.fader: "0",
            self.encoder: "0",
            self.meter_level: "0",
            self.top: self.default_label,
            self.bottom: "",
            self.lcd_color: look.color,
            **dict.fromkeys(self.leds.values(), "off"),
            self.buttons: None,
        }
        for entity in self._entities:
            if entity is not self.buttons:
                bridge.watch(entity, self._changed)

    def set_look(self, look: Look) -> None:
        super().set_look(look)
        self.default_label = look.label or ""
        self.default_color = look.color

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

    def held_meter(self, point: MeterPoint) -> Lit | None:
        """
        The level of the meter entity: 0..100 % over the levels of the meter, 100 % lights all LEDs (the red one too),
        nothing while not connected. Home Assistant sets the level, so the meter point means nothing here.
        """
        return _lit(self.meter_level.target_state) if self.connected else None

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
