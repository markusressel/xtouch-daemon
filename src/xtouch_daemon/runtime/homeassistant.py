"""
Channels, states and slots in Home Assistant (see "Home Assistant" in docs/design/channels-states-slots.md), for as
long as the configuration:

- `select.<ns>_mode`: the mode picked by hand, or `auto` for the rules.
- `binary_sensor.<ns>_state_<id>`: each state and mode, with the attributes `since`, `source` and `override`.
- `select.<ns>_state_<id>`: the override of each state that is no mode: `auto`, `on`, `off`.
- `switch.<ns>_state_<id>_input`: for states with `homeassistant = true`, what Home Assistant feeds into them.
- `binary_sensor.<ns>_<id>_shown`: whether a channel is on a slot.
- `sensor.<ns>_slot_<n>`: what slot n shows (a channel id, `app:<name>`, `person:<name>` or `none`), with the
  attributes `label`, `kind`, `via` and `reason`.

The entities of the channels and of `[controls]` are those of their controllers (see `runtime.binder`).
"""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.binary_sensor import MQTTBinarySensor
from haad_mqtt_autodiscovery.entity.select import MQTTSelect
from haad_mqtt_autodiscovery.entity.sensor import MQTTSensor
from haad_mqtt_autodiscovery.entity.switch import MQTTSwitch

from xtouch_daemon.config.slots import SlotsSetup
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.slots import SlotEngine
from xtouch_daemon.slots.inputs import App, Person
from xtouch_daemon.slots.resolver import SLOTS, Result, Shown
from xtouch_daemon.slots.states import Override

_LOGGER = logging.getLogger(__name__)

AUTO = "auto"

type Published = tuple[str, str | None]
"""The state of an entity and its attributes (JSON, None for none)."""


class SlotEntities:
    """
    The entities of the states, the mode, the channels and the slots of a configuration. `update()` publishes what
    changed after a step of the slots; choices in Home Assistant go to the engine, which `on_request` steps.
    """

    def __init__(self, bridge: MqttBridge, engine: SlotEngine, setup: SlotsSetup, on_input: Callable[[], None]):
        self.bridge = bridge
        self.engine = engine
        self.setup = setup
        self.on_input = on_input
        """Called when Home Assistant changed the input of a state: the slots look at it at the next step."""
        namespace, device = bridge.config.namespace, bridge.device
        scene = setup.scene
        self.mode = MQTTSelect(
            namespace,
            "mode",
            "Mode",
            options=[AUTO, *engine.modes],
            icon="mdi:view-dashboard-variant",
            device=device,
        )
        self.states = {
            name: MQTTBinarySensor(namespace, f"state_{name}", f"State {engine.mode_label(name)}", device=device)
            for name in scene.states
        }
        self.overrides = {
            name: MQTTSelect(
                namespace,
                f"state_{name}",
                f"State {engine.mode_label(name)} override",
                options=[value.value for value in Override],
                device=device,
                # the binary sensor of the state has the same identifier: the bridge tells them apart by unique id
                unique_id=f"{namespace}_state_{name}_override",
            )
            for name, state in scene.states.items()
            if not state.mode
        }
        self.inputs = {
            name: MQTTSwitch(namespace, f"state_{name}_input", f"State {engine.mode_label(name)} input", device=device)
            for name, state in scene.states.items()
            if state.homeassistant
        }
        self.shown = {
            name: MQTTBinarySensor(namespace, f"{name}_shown", f"{self._label(name)} shown", device=device)
            for name in scene.channels
        }
        self.slots = {
            slot: MQTTSensor(namespace, f"slot_{slot}", f"Slot {slot}", device=device, icon="mdi:tune-vertical")
            for slot in SLOTS
        }
        self.entities: dict[MQTTEntity, str | None] = {
            self.mode: AUTO,
            **dict.fromkeys(self.states.values(), "OFF"),
            **dict.fromkeys(self.overrides.values(), Override.AUTO.value),
            **dict.fromkeys(self.inputs.values(), "OFF"),
            **dict.fromkeys(self.shown.values(), "OFF"),
            **dict.fromkeys(self.slots.values(), "none"),
        }
        """Every entity with the state it starts with in Home Assistant."""
        bridge.watch_commands(self.mode, self._mode_chosen)
        for name, select in self.overrides.items():
            bridge.watch_commands(select, lambda value, name=name: self._override_chosen(name, value))
        for name, switch in self.inputs.items():
            bridge.watch(switch, lambda entity, name=name: self._input_changed(name, entity))
        self._published: dict[MQTTEntity, Published] = {}
        self._since: dict[tuple[str, float], str] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _label(self, channel: str) -> str:
        strip = self.setup.channels.get(channel)
        return getattr(strip, "label", None) or channel

    # -- from Home Assistant --------------------------------------------------------------------------------------

    def _mode_chosen(self, value: str) -> None:
        if value != AUTO and value not in self.engine.modes:
            return
        _LOGGER.info(f"Mode {value} (Home Assistant)")
        self.engine.pick_mode(None if value == AUTO else value)
        self.engine.on_request()

    def _override_chosen(self, name: str, value: str) -> None:
        if value not in Override:
            return
        _LOGGER.info(f"State {name}: override {value} (Home Assistant)")
        self.engine.set_override(name, Override(value))
        self.engine.on_request()

    def _input_changed(self, name: str, entity: MQTTEntity) -> None:
        on = (entity.state or "").upper() == "ON"
        inputs = self.engine.homeassistant
        self.engine.homeassistant = inputs | {name} if on else inputs - {name}
        if self.engine.homeassistant != inputs:
            self.on_input()

    # -- to Home Assistant ----------------------------------------------------------------------------------------

    def update(self, result: Result) -> None:
        """
        Publishes what changed, after a step of the slots. Everything after the broker was away (it may have the
        retained states of another run).
        """
        if not self.bridge.ready:
            self.forget()
            return
        for entity, published in self._wanted(result).items():
            if self._published.get(entity) != published:
                self._published[entity] = published
                self._send(entity, published)

    def forget(self) -> None:
        """The broker went away: the next `update()` publishes everything."""
        self._published.clear()

    def _wanted(self, result: Result) -> dict[MQTTEntity, Published]:
        engine = self.engine
        states = engine.simulation.states
        mode_pick = engine.simulation.engine.mode_pick
        overrides = engine.simulation.engine.overrides
        wanted: dict[MQTTEntity, Published] = {self.mode: (mode_pick or AUTO, None)}
        since = states.since if states is not None else {}
        reasons = states.reasons if states is not None else {}
        for name, sensor in self.states.items():
            on = engine.value(name)
            attributes = {
                "since": self._wall_time(name, since[name]) if name in since else None,
                "source": reasons.get(name) if on else None,
                "override": overrides.get(name, Override.AUTO).value,
            }
            wanted[sensor] = ("ON" if on else "OFF", json.dumps(attributes))
        for name, select in self.overrides.items():
            wanted[select] = (overrides.get(name, Override.AUTO).value, None)
        shown = {shown.channel for shown in result.slots.values() if shown.channel is not None}
        for name, sensor in self.shown.items():
            wanted[sensor] = ("ON" if name in shown else "OFF", None)
        for slot, sensor in self.slots.items():
            wanted[sensor] = self._slot(slot, result.slots[slot], result.why[slot])
        return wanted

    def _slot(self, slot: int, shown: Shown, why: tuple[str, ...]) -> Published:
        stack = self.setup.scene.stacks[slot]
        via = stack[shown.candidate].show if shown.candidate is not None else None
        match shown.member:
            case App(name=name):
                value, kind, label = f"app:{name}", "app", name
            case Person(channel=None, name=name):
                value, kind, label = f"person:{name}", "person", name
            case _ if shown.channel is not None:
                value, kind, label = shown.channel, "channel", self._label(shown.channel)
            case _:
                value, kind, label = "none", "none", ""
        attributes = {"label": label, "kind": kind, "via": via, "reason": why[-1] if why else None}
        return value, json.dumps(attributes)

    def _wall_time(self, name: str, since: float) -> str:
        """When a state got its value (a time of the engine's clock), as an ISO time; the same for the same value."""
        key = (name, since)
        if key not in self._since:
            self._since[key] = self.engine.wall_time(since)
        return self._since[key]

    def _send(self, entity: MQTTEntity, published: Published) -> None:
        state, attributes = published

        async def send() -> None:
            await self.bridge.set_state(entity, state)
            if attributes is not None:
                await self.bridge.set_attributes(entity, attributes)

        self._run(send(), entity.unique_id)

    def _run(self, coroutine: Coroutine[Any, Any, None], name: str) -> None:
        task = asyncio.create_task(coroutine, name=f"mqtt {name}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def close(self) -> None:
        self.bridge.unwatch(self.mode)
        for entity in (*self.overrides.values(), *self.inputs.values()):
            self.bridge.unwatch(entity)
        for task in self._tasks:
            task.cancel()
