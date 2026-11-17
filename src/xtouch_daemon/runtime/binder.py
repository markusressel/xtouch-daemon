"""
The slots on the device, natively (see "The daemon" in docs/design/channels-states-slots.md): a controller per
channel for as long as the configuration, one per application of `auto` and per person while they are members, and
a binder that puts on each strip of the device the controller of what its slot shows. Only slots whose result
changed are bound again: the others keep their controller, their fader and their texts.
"""

import asyncio
import itertools
from collections.abc import Callable, Mapping

from haad_mqtt_autodiscovery.entity import MQTTEntity

from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.media import MediaPlayers
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config.audio_strips import AutoStripConfig
from xtouch_daemon.config.layout_strips import VoipStripConfig
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import StripConfig
from xtouch_daemon.config.values import EncoderMode, default_encoder
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.strip import VirtualStrip
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.runtime.slots import SlotEngine
from xtouch_daemon.slots.inputs import App, Person
from xtouch_daemon.slots.resolver import SLOTS, Result, Shown
from xtouch_daemon.strips import EmptyStrip, build_strip, look_of
from xtouch_daemon.strips.apps import AutoStrip
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv, VolumeStrip
from xtouch_daemon.strips.voip import VoipSeat, VoipSeats, VoipStrip
from xtouch_daemon.system.launch import Launcher
from xtouch_daemon.system.processes import running_processes
from xtouch_daemon.voip.provider import VoipProvider

PROCESS_INTERVAL = 2.0
"""How often the processes are checked while a controller launches applications (`launch`)."""

type Key = tuple[str, str]
"""What a strip of the device shows: ("channel", id), ("app", name), ("person", id) or ("empty", slot)."""
type Place = tuple[EncoderMode, int | None, int | None]
"""What the encoder of a controller does and its volume range: those of the place it is on."""


def key_of(slot: int, shown: Shown) -> Key:
    match shown.member:
        case App(name=name):
            return "app", name
        case Person(channel=None, id=person):
            return "person", person
        case _:
            return ("channel", shown.channel) if shown.channel is not None else ("empty", str(slot))


def place_of(strip: StripConfig) -> Place | None:
    """None for a strip without a volume."""
    if not isinstance(strip, BaseStripConfig):
        return None
    return strip.encoder or default_encoder(strip.type, strip.fader), strip.min_volume, strip.max_volume


class SlotMixer:
    """
    The controllers of a configuration of channels, states and slots, bound to the strips of the desk as the
    `SlotEngine` says (`apply()`). It stands in for the `Mixer` of strips and layouts in the daemon.
    """

    def __init__(
        self,
        surface: Surface,
        backend: AudioBackend,
        config: Config,
        engine: SlotEngine,
        desk: Desk,
        voip: VoipProvider,
        bridge: MqttBridge | None = None,
        players: MediaPlayers | None = None,
        shared_entities: Mapping[MQTTEntity, str | None] | None = None,
        preview: bool = False,
        launcher: Launcher | None = None,
        processes: Callable[[], frozenset[str]] = running_processes,
    ):
        assert config.slots is not None, "only for a configuration of slots"
        self.setup = config.slots
        self.config = config
        self.engine = engine
        self.desk = desk
        self.surface = surface
        self.bridge = bridge
        self.voip = voip
        self.shared_entities = dict(shared_entities or {})
        self.preview = preview
        self._scan_processes = processes
        self.processes: frozenset[str] = frozenset()
        """The processes that run, while a channel launches an application (`launch`), every PROCESS_INTERVAL."""
        self.env = StripEnv(
            backend, config.behavior, bridge, players, voip, launcher or Launcher(), lambda: self.processes
        )
        self.state: AudioState = DISCONNECTED
        self._numbers = itertools.count()
        self.places: dict[Key, Place] = {}
        """Where each controller with a volume is now (see `_dress()`)."""
        self.channels: dict[str, StripController] = {
            name: self._build(("channel", name), strip, Identity(name, self._look(strip).label or name))
            for name, strip in self.setup.channels.items()
        }
        """A controller per channel, for as long as the configuration."""
        self.members: dict[Key, StripController] = {}
        """A controller per application of `auto` and per person without a channel, made when they first show."""
        self.empty = {
            slot: self._build(("empty", str(slot)), None, Identity(f"slot_{slot}", f"Slot {slot}")) for slot in SLOTS
        }
        """What a dark slot shows."""
        self.bound: dict[int, tuple[Key, int | None]] = {}
        """What each slot (from 1) shows now: the key of its controller and its candidate."""
        self.watches_processes = any(controller.launches for controller in self.channels.values())
        if self.watches_processes:
            self.processes = processes()
        self.entities = {
            entity: default for controller in self.channels.values() for entity, default in controller.entities.items()
        }
        """The entities of the channels in Home Assistant, for the MQTT bridge: the same for the whole configuration."""
        if bridge is not None:
            bridge.bind(self.entities)
        voip.subscribe(self.refresh)

    def _build(self, key: Key, strip: StripConfig | None, identity: Identity) -> StripController:
        view = VirtualStrip(self.surface, next(self._numbers))
        if strip is None:
            return EmptyStrip(view, self.env, identity, Look(meter=False))
        seat = None
        if isinstance(strip, VoipStripConfig):
            seat = VoipSeat(VoipSeats(self.voip, [strip.person], self.refresh), 0)
        if (place := place_of(strip)) is not None:
            self.places[key] = place
        return build_strip(strip, view, self.env, self.config.aliases, identity, self._look(strip), seat)

    def _look(self, strip: StripConfig) -> Look:
        return look_of(strip, self.config.meter_point(strip))

    # -- what shows where ------------------------------------------------------------------------------------------

    def apply(self, result: Result) -> None:
        """
        Puts on each slot the controller of what it shows. Only slots whose result changed are touched: the others
        keep their controller, so their texts, fader and LEDs stay as they are.
        """
        for slot, shown in result.slots.items():
            key = key_of(slot, shown)
            before = self.bound.get(slot)
            if before == (key, shown.candidate):
                continue
            controller = self._controller(key, slot, shown)
            self.bound[slot] = (key, shown.candidate)
            self._dress(controller, key, slot, shown.candidate)
            controller.update(self.state)
            view = controller.strip
            assert isinstance(view, VirtualStrip)
            device = self.surface.strips[slot - 1]
            if (old := self._at(slot)) is not None and old is not controller:
                old_view = old.strip
                assert isinstance(old_view, VirtualStrip)
                if old_view.target is device:
                    # (a controller that moved to a slot handled before is on its new strip already)
                    old_view.bind(None)
            if view.target is not device:
                view.bind(device)
            self.desk.bind(slot - 1, controller, controller.look.meter_point)
        self._close_gone()
        self.desk.watch(self.state)

    def _at(self, slot: int) -> StripController | None:
        presenter = self.desk.presenters[slot - 1]
        assert presenter is None or isinstance(presenter, StripController)
        return presenter

    def _controller(self, key: Key, slot: int, shown: Shown) -> StripController:
        kind, name = key
        if kind == "channel":
            return self.channels[name]
        if kind == "empty":
            return self.empty[slot]
        if key not in self.members:
            if isinstance(shown.member, App):
                # built for the place it shows first; `_dress()` moves it to the others
                place = self.setup.strips[(slot, shown.candidate if shown.candidate is not None else -1, None)]
                assert isinstance(place, AutoStripConfig)
                controller = self._build(key, place, Identity(f"app_{name}", name))
                assert isinstance(controller, AutoStrip)
                controller.assign(self.engine.observer.apps.get(name, name))
            else:
                assert isinstance(shown.member, Person)
                person = shown.member.name
                controller = self._build(key, self.setup.person(person), Identity(f"person_{name}", person))
            self.members[key] = controller
        return self.members[key]

    def _dress(self, controller: StripController, key: Key, slot: int, candidate: int | None) -> None:
        """
        The look of the place the controller is on now, and its encoder and volume range. People on slots of `auto`
        keep the look of `[people]`.
        """
        if candidate is None or key[0] in ("empty", "person"):
            return
        place = self.setup.strips[(slot, candidate, key[1] if key[0] == "channel" else None)]
        controller.set_look(self._look(place))
        if isinstance(controller, AutoStrip):
            controller.slot = self.engine.slot(slot - 1)
        if not isinstance(controller, VolumeStrip):
            return
        new = place_of(place)
        assert new is not None, "a controller with a volume shows in places with one"
        if new != self.places[key]:
            controller.set_place(*new)
            self.places[key] = new

    def _close_gone(self) -> None:
        """Closes the controllers of members that show nowhere and are no members any more."""
        shown = {key for key, _ in self.bound.values()}
        pools = self.engine.simulation.pools
        alive = {("app", app) for app in pools.playing} | {("person", person.id) for person in pools.people}
        for key in [key for key in self.members if key not in shown and key not in alive]:
            self.members.pop(key).close()
            self.places.pop(key, None)

    # -- input ----------------------------------------------------------------------------------------------------

    def on_state(self, state: AudioState) -> None:
        self.state = state
        self.refresh()

    def refresh(self) -> None:
        for controller in self.all_controllers:
            controller.update(self.state)
        self.desk.watch(self.state)

    @property
    def all_controllers(self) -> list[StripController]:
        return [*self.channels.values(), *self.members.values(), *self.empty.values()]

    @property
    def controllers(self) -> list[StripController]:
        """The controllers on the strips of the device, from the left (none before the first `apply()`)."""
        return [controller for slot in SLOTS if (controller := self._at(slot)) is not None]

    @property
    def placement(self) -> tuple[int | None, ...]:
        """Each strip of the device shows its slot."""
        return tuple(range(protocol.STRIPS))

    @property
    def voip_names(self) -> tuple[str | None, ...]:
        """For each strip of the device, the name of the participant it shows (None for nobody)."""
        return tuple(
            person.name
            if isinstance(controller, VoipStrip) and (person := controller.participant) is not None
            else None
            for controller in self.controllers
        )

    # -- running --------------------------------------------------------------------------------------------------

    async def run(self) -> None:
        """Announces the entities of the channels, then follows the processes for channels with `launch`."""
        if self.bridge is not None:
            await self.bridge.set_entities(self.entities | self.shared_entities, preview=self.preview)
        while self.watches_processes:
            await asyncio.sleep(PROCESS_INTERVAL)
            # a launched application shows up, the LED of a launch that took too long stops flashing
            self.processes = self._scan_processes()
            self.refresh()
        # nothing to follow: until the mixer is closed
        await asyncio.Event().wait()

    def close(self) -> None:
        self.desk.unbind(self.all_controllers)
        self.voip.unsubscribe(self.refresh)
        for controller in self.all_controllers:
            controller.close()
            assert isinstance(controller.strip, VirtualStrip)
            # the next mixer draws on the device
            controller.strip.target = None
