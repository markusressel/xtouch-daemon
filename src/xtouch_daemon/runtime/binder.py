"""
The slots on the device, natively (see docs/development/design/slots/daemon.md): a controller
per channel for as long as the configuration, one per application of `auto` and per person while they are members, and
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
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import EmptyStripConfig, StripConfig
from xtouch_daemon.config.values import EncoderMode, default_encoder
from xtouch_daemon.config.voip_strips import VoipStripConfig
from xtouch_daemon.hardware.strip import Claimable, VirtualStrip
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.controls import Controls
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.runtime.slots import SlotEngine
from xtouch_daemon.slots.inputs import App, Device, Person
from xtouch_daemon.slots.resolver import SLOTS, Result, Shown
from xtouch_daemon.strips import build_strip, look_of
from xtouch_daemon.strips.apps import AutoStrip
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv, VolumeStrip
from xtouch_daemon.strips.custom import CustomStrip
from xtouch_daemon.system.commands import Commands
from xtouch_daemon.system.launch import Launcher
from xtouch_daemon.system.processes import running_processes
from xtouch_daemon.voip.provider import VoipProvider

PROCESS_INTERVAL = 2.0
"""How often the processes are checked while a controller launches applications (`launch`)."""

type Key = tuple[str, str]
"""
What a strip of the device shows: ("channel", id), ("app", name), ("person", id), ("device", node name) or ("empty",
slot).
"""
type Place = tuple[EncoderMode, int | None, int | None]
"""What the encoder of a controller does and its volume range: those of the place it is on."""


def key_of(slot: int, shown: Shown) -> Key:
    match shown.member:
        case App(name=name):
            return "app", name
        case Person(channel=None, id=person):
            return "person", person
        case Device(name=name):
            return "device", name
        case _:
            return ("channel", shown.channel) if shown.channel is not None else ("empty", str(slot))


def _entity_id(name: str) -> str:
    """A node name as part of an id in Home Assistant: `bluez_output.AA_BB.1` is `bluez_output_aa_bb_1`."""
    return "".join(char if char.isalnum() else "_" for char in name.lower())


def place_of(strip: StripConfig) -> Place | None:
    """None for a strip without a volume."""
    if not isinstance(strip, BaseStripConfig):
        return None
    # bindings: done by the audio strips (an encoder bound to a program)
    encoder = strip.encoder if isinstance(strip.encoder, str) else default_encoder(strip.type, strip.fader)
    return encoder, strip.min_volume, strip.max_volume


class SlotMixer:
    """
    The controllers of a configuration of channels, states and slots, bound to the strips of the desk as the
    `SlotEngine` says (`apply()`).
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
        commands: Commands | None = None,
    ):
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
            backend,
            config.behavior,
            bridge,
            players,
            voip,
            launcher or Launcher(),
            lambda: self.processes,
            engine,
            self._solo,
            commands if commands is not None else Commands(),
        )
        self._soloed: list[VolumeStrip] = []
        """The strips `mute_others` muted, unmuted again when its button is let go."""
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
        self.controls = Controls(
            self.setup.scene,
            desk,
            engine,
            bridge,
            self.env.launcher,
            lambda: self.processes,
            config.behavior.encoder_step,
            {name: controller for name, controller in self.channels.items() if isinstance(controller, CustomStrip)},
            self.env.commands,
        )
        """The `[controls]` of the slots: claims on the strips of the desk."""
        self.controls.on_change = self.controls.show
        self.watches_processes = self.controls.launches or any(
            controller.launches for controller in self.channels.values()
        )
        if self.watches_processes:
            self.processes = processes()
        self.entities = {
            entity: default for controller in self.channels.values() for entity, default in controller.entities.items()
        } | self.controls.entities
        """
        The entities of the channels and the controls in Home Assistant, for the MQTT bridge: the same for the whole
        configuration.
        """
        if bridge is not None:
            bridge.bind(self.entities)
        voip.subscribe(self.refresh)

    def _build(self, key: Key, strip: StripConfig | None, identity: Identity) -> StripController:
        view = VirtualStrip(self.surface, next(self._numbers))
        if strip is None:
            strip = EmptyStripConfig(type="empty")
        if (place := place_of(strip)) is not None:
            self.places[key] = place
        return build_strip(strip, view, self.env, self.config.aliases, identity, self._look(strip), self.voip)

    def _look(self, strip: StripConfig) -> Look:
        return look_of(strip, self.config.meter_point(strip))

    # -- what shows where ------------------------------------------------------------------------------------------

    def apply(self, result: Result, flash: float = 0.0) -> None:
        """
        Puts on each slot the controller of what it shows. Only slots whose result changed are touched: the others
        keep their controller, so their texts, fader and LEDs stay as they are. A slot that shows another candidate
        flashes its label and why for `flash` seconds (0: not at all). The controls of the slots claim what their
        `when` says (see `runtime.controls`).
        """
        states = self.engine.active.states
        self.controls.apply(states.values if states is not None else {})
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
                # what the controls of the slot claim stays theirs
                self._give(controller, self.controls.taken(slot))
                view.bind(device)
            self.desk.bind(slot - 1, controller, controller.look.meter_point)
            if flash > 0 and before is not None and before[1] != shown.candidate:
                self.surface.flash(slot - 1, view.text[0], self._why(slot, before[1], shown.candidate), flash)
        self._close_gone()
        self._hand_out_claims()
        self.desk.watch(self.state)

    def _hand_out_claims(self) -> None:
        """Each controller learns what the controls of its slot take (none off the device); the claims show theirs."""
        slots = {id(controller): slot for slot in SLOTS if (controller := self._at(slot)) is not None}
        for controller in self.all_controllers:
            slot = slots.get(id(controller))
            self._give(controller, self.controls.taken(slot) if slot is not None else frozenset())
        self.controls.show()

    @staticmethod
    def _give(controller: StripController, taken: frozenset[Claimable]) -> None:
        if controller.taken == taken:
            return
        controller.set_taken(taken)
        view = controller.strip
        assert isinstance(view, VirtualStrip)
        view.mask(taken)

    def _why(self, slot: int, before: int | None, now: int | None) -> str:
        """Why a slot shows another candidate, in a word: the `when` of the new one, or the one that ended."""
        stack = self.setup.scene.stacks[slot]
        if now is not None and (when := stack[now].when) is not None:
            return when.text
        if before is not None and (when := stack[before].when) is not None:
            return f"not {when.text}"
        return ""

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
            elif isinstance(shown.member, Device):
                device = shown.member
                place = self.setup.strips[(slot, shown.candidate if shown.candidate is not None else -1, None)]
                strip = self.setup.device(place, device.name, device.direction)
                controller = self._build(key, strip, Identity(f"device_{_entity_id(name)}", str(device)))
            else:
                assert isinstance(shown.member, Person)
                person = shown.member.name
                controller = self._build(key, self.setup.person(person), Identity(f"person_{name}", person))
            self.members[key] = controller
        return self.members[key]

    def _dress(self, controller: StripController, key: Key, slot: int, candidate: int | None) -> None:
        """
        The look of the place the controller is on now, and its encoder and volume range. People look as their place
        of `people` says, and on slots of `auto` as `[pool.people]` says.
        """
        if candidate is None or key[0] == "empty":
            return
        place = self.setup.strips[(slot, candidate, key[1] if key[0] == "channel" else None)]
        if key[0] == "person":
            controller.set_look(self._look(place if isinstance(place, VoipStripConfig) else self.setup.person(key[1])))
            return
        if key[0] == "device":
            # the look of the place; its label stays the device's own
            member = self.engine.member(slot)
            assert isinstance(member, Device)
            place = self.setup.device(place, member.name, member.direction)
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
        pools = self.engine.active.pools
        alive = (
            {("app", app) for app in pools.playing}
            | {("person", person.id) for person in pools.people}
            | {("device", device.name) for device in pools.sound_devices}
        )
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
        self.controls.show()
        self.desk.watch(self.state)

    @property
    def all_controllers(self) -> list[StripController]:
        return [*self.channels.values(), *self.members.values(), *self.empty.values()]

    @property
    def controllers(self) -> list[StripController]:
        """The controllers on the strips of the device, from the left (none before the first `apply()`)."""
        return [controller for slot in SLOTS if (controller := self._at(slot)) is not None]

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

    def _solo(self, soloist: StripController, on: bool) -> None:
        """
        `mute_others`: mutes what the other slots show while the button is held (what is muted already stays so), and
        unmutes it again when the button is let go.
        """
        for strip in self._soloed:
            strip.run_command(strip.apply_mute(False), "the solo ends")
        self._soloed = []
        if not on:
            return
        for slot in SLOTS:
            strip = self._at(slot)
            if not isinstance(strip, VolumeStrip) or strip is soloist or not strip.active or strip.level is None:
                continue
            if not strip.level.muted:
                self._soloed.append(strip)
                strip.run_command(strip.apply_mute(True), f"a solo of {soloist.identity.name}")

    def close(self) -> None:
        self.controls.close()
        self.desk.unbind(self.all_controllers)
        self.voip.unsubscribe(self.refresh)
        for controller in self.all_controllers:
            controller.close()
            assert isinstance(controller.strip, VirtualStrip)
            # the next mixer draws on the device
            controller.strip.target = None
