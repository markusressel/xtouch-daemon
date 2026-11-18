"""
The controls of the slots (`[controls]`, see "Controls" in docs/development/design/channels-states-slots.md): what a
fader, encoder or button of a slot does whatever the slot shows. Each entry is a claim on the `Desk`'s strip of the slot
while its `when` holds (the first of a slot whose `when` holds); a slot under a finger keeps its claim until it is let
go. A claim shows what it takes (the fader, the ring, the LEDs of its buttons); the controller of what the slot shows
shows the rest. Their entities in Home Assistant are there for as long as the configuration, whatever the slots show.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.select import MQTTSelect

from xtouch_daemon.hardware.protocol import Button, Led, RingMode
from xtouch_daemon.hardware.strip import CLAIMABLE_BUTTONS, Claimable, Strip
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.slots.model import DEFAULT, ControlsConfig, Launch, Scene
from xtouch_daemon.strips.base import Identity
from xtouch_daemon.strips.homeassistant import LEDS, EncoderLink, FaderLink, StripEntities
from xtouch_daemon.system.launch import LaunchButton, Launcher

_LOGGER = logging.getLogger(__name__)

HOME_ASSISTANT = "homeassistant"
BUTTONS: dict[Claimable, Button] = {name: button for button, name in CLAIMABLE_BUTTONS.items()}
PARTS: tuple[Claimable, ...] = ("fader", "encoder", *BUTTONS)


class Actions(Protocol):
    """What the buttons of controls ask of the slots (the `SlotEngine`): modes and overrides."""

    @property
    def mode(self) -> str: ...
    def value(self, name: str) -> bool: ...
    def cycle_modes(self) -> None: ...
    def choose_mode(self, mode: str) -> None: ...
    def toggle(self, name: str) -> None: ...


def key_of(slot: int, config: ControlsConfig) -> str:
    """What names the entities of controls: their `id`, else `slot_<n>`."""
    return config.id or f"slot_{slot}"


class ControlEntities:
    """
    The entities of the controls of a slot that share a key (`key_of()`), for every entry of the slot with it: a number
    for a fader and an encoder in Home Assistant, events for their touches and pushes and the presses of buttons, and
    a select for the LED of each button.
    """

    def __init__(self, bridge: MqttBridge, identity: Identity, entries: list[ControlsConfig]):
        self.bridge = bridge
        entities = StripEntities(bridge, identity)
        fader = any(entry.fader == HOME_ASSISTANT for entry in entries)
        encoder = any(entry.encoder == HOME_ASSISTANT for entry in entries)
        buttons = [
            button
            for name, button in BUTTONS.items()
            if any(getattr(entry, name) == HOME_ASSISTANT for entry in entries)
        ]
        self.fader = entities.number("fader") if fader else None
        self.encoder = entities.number("encoder") if encoder else None
        event_types = [
            *(["fader_touched", "fader_released"] if fader else []),
            *(["encoder_pressed", "encoder_released"] if encoder else []),
            *(f"{button.name.lower()}_{action}" for button in buttons for action in ("pressed", "released")),
        ]
        self.events = entities.events(event_types) if event_types else None
        self.leds = {
            button: MQTTSelect(
                entities.namespace,
                f"{identity.id}_{button.name.lower()}_led",
                f"{identity.name} {button.name.lower()} LED",
                options=list(LEDS),
                device=entities.device,
            )
            for button in buttons
        }
        numbers: list[MQTTEntity] = [entity for entity in (self.fader, self.encoder) if entity is not None]
        self.entities: dict[MQTTEntity, str | None] = {
            **dict.fromkeys(numbers, "0"),
            **dict.fromkeys(self.leds.values(), "off"),
            **({self.events: None} if self.events is not None else {}),
        }
        self.watched = [*numbers, *self.leds.values()]

    def watch(self, on_change: Callable[[], None]) -> None:
        for entity in self.watched:
            self.bridge.watch(entity, lambda _: on_change())

    def close(self) -> None:
        for entity in self.watched:
            self.bridge.unwatch(entity)


class SlotClaim:
    """
    One entry of the controls of a slot: the controls it claims, what they do, and what they show on the strip of the
    device (`show()`).
    """

    def __init__(
        self,
        slot: int,
        index: int,
        config: ControlsConfig,
        strip: Strip,
        entities: ControlEntities | None,
        actions: Actions,
        launcher: Launcher,
        processes: Callable[[], frozenset[str]],
        encoder_step: int,
    ):
        self.slot = slot
        self.config = config
        self.strip = strip
        self.entities = entities
        self.actions = actions
        self.processes = processes
        self.what = f"controls.{slot}" + (f"[{index}]" if index else "")
        self.taken: frozenset[Claimable] = frozenset(part for part in PARTS if part in config.claimed)
        self.fader: FaderLink | None = None
        self.encoder: EncoderLink | None = None
        if config.fader == HOME_ASSISTANT:
            assert entities is not None
            assert entities.fader is not None
            self.fader = FaderLink(strip, entities.fader)
        if config.encoder == HOME_ASSISTANT:
            assert entities is not None
            assert entities.encoder is not None
            self.encoder = EncoderLink(strip, entities.encoder, encoder_step)
        self.launches = {
            button: LaunchButton(action.launch, launcher, self.what, action.launch_when_running)
            for name, button in BUTTONS.items()
            if isinstance(action := getattr(config, name), Launch)
        }
        self._tasks: set[asyncio.Task[None]] = set()

    def action(self, button: Button) -> str | Launch | None:
        return getattr(self.config, CLAIMABLE_BUTTONS[button]) if button in CLAIMABLE_BUTTONS else None

    @property
    def connected(self) -> bool:
        """Whether Home Assistant is there with the states of the numbers it takes (always, without any)."""
        links = [link for link in (self.fader, self.encoder) if link is not None]
        return not links or (
            self.entities is not None
            and self.entities.bridge.ready
            and None not in [link.out.current for link in links]
        )

    # -- showing --------------------------------------------------------------------------------------------------

    def show(self) -> None:
        """Shows what it takes on the strip of the device: the fader, the ring, the LEDs of its buttons."""
        connected = self.connected
        if self.fader is not None and connected:
            self.fader.show()
        if self.encoder is not None:
            self.strip.set_ring(*(self.encoder.ring() if connected else (0, RingMode.DOT)))
        for name, button in BUTTONS.items():
            if (action := getattr(self.config, name)) is not None:
                self.strip.set_led(button, self._led(button, action))

    def _led(self, button: Button, action: str | Launch) -> Led:
        if isinstance(action, Launch):
            launch = self.launches[button]
            return launch.led(launch.program_runs(self.processes()))
        if action == HOME_ASSISTANT:
            assert self.entities is not None
            led = self.entities.leds[button].target_state
            return LEDS.get(led or "", Led.OFF) if self.entities.bridge.ready else Led.OFF
        if action == "cycle_modes":
            return Led.ON if self.actions.mode != DEFAULT else Led.OFF
        if action.startswith("mode:"):
            return Led.ON if self.actions.mode == action.removeprefix("mode:") else Led.OFF
        return Led.ON if self.actions.value(action.removeprefix("toggle:")) else Led.OFF

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        assert self.fader is not None
        if self.connected:
            self.fader.moved(fraction)

    # the desk hands it only the controls it takes: a fader and an encoder only in Home Assistant

    def on_touch(self, touched: bool) -> None:
        assert self.fader is not None
        self.fader.touch(touched)
        self._event("fader_touched" if touched else "fader_released")

    def on_encoder(self, steps: int) -> None:
        assert self.encoder is not None
        if self.connected:
            self.encoder.turn(steps)

    def on_encoder_press(self, pressed: bool) -> None:
        self._event("encoder_pressed" if pressed else "encoder_released")

    def on_button(self, button: Button, pressed: bool) -> None:
        action = self.action(button)
        if action == HOME_ASSISTANT:
            self._event(f"{button.name.lower()}_{'pressed' if pressed else 'released'}")
            return
        if not pressed or action is None:
            return
        if isinstance(action, Launch):
            launch = self.launches[button]
            launch.press(launch.program_runs(self.processes()))
            self.show()
        elif action == "cycle_modes":
            self.actions.cycle_modes()
        elif action.startswith("mode:"):
            self.actions.choose_mode(action.removeprefix("mode:"))
        else:
            self.actions.toggle(action.removeprefix("toggle:"))

    def _event(self, event_type: str) -> None:
        if self.entities is None or self.entities.events is None or not self.entities.bridge.ready:
            return
        task = asyncio.create_task(self.entities.events.trigger(event_type), name=f"{self.what}: {event_type}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def close(self) -> None:
        for link in (self.fader, self.encoder):
            if link is not None:
                link.close()
        for task in self._tasks:
            task.cancel()


class Controls:
    """
    The `[controls]` of a configuration on the desk: per slot its entries, the one that acts now as a claim on the
    strip of the slot (`apply()`), and their entities.
    """

    def __init__(
        self,
        scene: Scene,
        desk: Desk,
        actions: Actions,
        bridge: MqttBridge | None,
        launcher: Launcher,
        processes: Callable[[], frozenset[str]],
        encoder_step: int,
    ):
        self.scene = scene
        self.desk = desk
        self.on_change: Callable[[], None] = lambda: None
        """Called when Home Assistant changed one of their entities."""
        self.entities: dict[MQTTEntity, str | None] = {}
        """Their entities in Home Assistant, for the MQTT bridge."""
        self._links: list[ControlEntities] = []
        self.claims: dict[int, tuple[SlotClaim, ...]] = {}
        for slot, entries in scene.controls.items():
            by_key: dict[str, ControlEntities] = {}
            for key in dict.fromkeys(key_of(slot, entry) for entry in entries):
                with_key = [entry for entry in entries if key_of(slot, entry) == key]
                if not any(HOME_ASSISTANT in (entry.fader, entry.encoder, *_buttons(entry)) for entry in with_key):
                    continue
                assert bridge is not None, "controls in Home Assistant need [mqtt] (checked when the file is loaded)"
                name = key if key != f"slot_{slot}" else f"Slot {slot}"
                entities = by_key[key] = ControlEntities(bridge, Identity(key, name), with_key)
                entities.watch(lambda: self.on_change())
                self._links.append(entities)
                self.entities |= entities.entities
            self.claims[slot] = tuple(
                SlotClaim(
                    slot,
                    index,
                    entry,
                    desk.surface.strips[slot - 1],
                    by_key.get(key_of(slot, entry)),
                    actions,
                    launcher,
                    processes,
                    encoder_step,
                )
                for index, entry in enumerate(entries)
            )
        self.active: dict[int, SlotClaim | None] = dict.fromkeys(self.claims)
        """The claim on each slot with controls, None while none of its entries' `when` holds."""

    @property
    def launches(self) -> bool:
        """Whether a button launches an application: then the processes are watched."""
        return any(claim.launches for claims in self.claims.values() for claim in claims)

    def apply(self, states: Mapping[str, bool]) -> None:
        """
        Puts on each slot the first entry whose `when` holds in `states`; a slot under a finger keeps its claim until
        it is let go.
        """
        held = self.desk.held_slots()
        for slot, claims in self.claims.items():
            if slot in held:
                continue
            active = next(
                (
                    claim
                    for index, claim in enumerate(claims)
                    if (condition := self.scene.control_conditions.get((slot, index))) is None
                    or condition.holds(states, lambda _: False)
                ),
                None,
            )
            if active is not self.active[slot]:
                _LOGGER.debug(f"Slot {slot}: controls {active.what if active is not None else 'none'}")
                self.active[slot] = active
                self.desk.claim(slot - 1, active)

    def taken(self, slot: int) -> frozenset[Claimable]:
        """The controls of a slot (from 1) that its controls take now."""
        claim = self.active.get(slot)
        return claim.taken if claim is not None else frozenset()

    def show(self) -> None:
        for claim in self.active.values():
            if claim is not None:
                claim.show()

    def close(self) -> None:
        for slot, claim in self.active.items():
            if claim is not None:
                self.desk.claim(slot - 1, None)
        for claims in self.claims.values():
            for claim in claims:
                claim.close()
        for entities in self._links:
            entities.close()


def _buttons(entry: ControlsConfig) -> tuple[str | Launch | None, ...]:
    return entry.select, entry.rec, entry.solo
