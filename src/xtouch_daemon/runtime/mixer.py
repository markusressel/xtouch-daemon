"""
The mixer: the strips of one configuration, fed with every audio state; the desk hands them the events of the strips
of the device they are on, and shows their meters. A new configuration gets a new mixer on the same desk and sound
server connection. With `collapse`, the strips of the configuration move between the strips of the device (see
`placement.py`).
"""

import asyncio
import time
from collections.abc import Callable, Mapping

from haad_mqtt_autodiscovery.entity import MQTTEntity

from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.media import MediaPlayers
from xtouch_daemon.audio.meter import PW_RECORD
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config.layout_strips import VoipStripConfig
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.strips import StripConfig, collapses
from xtouch_daemon.config.values import DEFAULT_LAYOUT, MeterPoint
from xtouch_daemon.hardware.strip import VirtualStrip
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.runtime.placement import Flow, Placement
from xtouch_daemon.strips import build_strip, launch_button
from xtouch_daemon.strips.apps import AppGroupStrip, AutoAssigner, AutoSlot, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv
from xtouch_daemon.strips.voip import VoipSeat, VoipSeats, VoipStrip
from xtouch_daemon.system.launch import LaunchButton, Launcher
from xtouch_daemon.system.processes import running_processes
from xtouch_daemon.voip.provider import VoipProvider

TICK = 0.1
"""How often the mixer looks whether a strip collapsed after its hold time."""
AUTO_INTERVAL = 1.0
"""How often `auto` strips are checked for applications whose hold time is over."""
PROCESS_INTERVAL = 2.0
"""How often the processes are checked while a strip launches applications (`launch`), like the layout rules."""


class Mixer:
    def __init__(
        self,
        surface: Surface,
        backend: AudioBackend,
        config: Config,
        clock: Callable[[], float] = time.monotonic,
        capture_command: str = PW_RECORD,
        bridge: MqttBridge | None = None,
        players: MediaPlayers | None = None,
        layout: str = DEFAULT_LAYOUT,
        voip: VoipProvider | None = None,
        shared_entities: Mapping[MQTTEntity, str | None] | None = None,
        keep: frozenset[str] = frozenset(),
        preview: bool = False,
        launcher: Launcher | None = None,
        processes: Callable[[], frozenset[str]] = running_processes,
        desk: Desk | None = None,
    ):
        """
        `desk` is the desk of the daemon; a mixer on its own makes one for the surface, whose meters capture with
        `capture_command`, and runs and closes it. `layout` is the layout whose
        strips the mixer drives, `voip` the provider of the participants for `voip`
        strips. `shared_entities` are entities in Home Assistant that are not of a strip (e.g. the layout select),
        `keep` the unique ids of entities of the other layouts, which stay in Home Assistant. `preview`: the
        configuration is a live preview of the GUI (see `MqttBridge.set_entities()`). `launcher` starts the
        applications of strips with `launch`, `processes` tells the processes that run, which those need.
        """
        self.bridge = bridge
        self.layout = layout
        self.voip = voip
        self.shared_entities = dict(shared_entities or {})
        self.keep = keep
        self.preview = preview
        self._scan_processes = processes
        self.processes: frozenset[str] = frozenset()
        """The processes that run, while a strip launches an application (`launch`), every PROCESS_INTERVAL."""
        env = StripEnv(backend, config.behavior, bridge, players, voip, launcher or Launcher(), lambda: self.processes)
        self.surface = surface
        self._own_desk = desk is None
        self.desk = desk if desk is not None else Desk(surface, capture_command=capture_command)
        self.state: AudioState = DISCONNECTED
        self.controllers: list[StripController] = []
        strips = config.all_strips(layout)
        self.strips = [VirtualStrip(surface, index) for index in range(len(strips))]
        """What each strip of the configuration shows, on the strip of the device it is on (see `flow`)."""
        seats = self._voip_seats(strips, self.strips, env)
        for strip_config, strip, seat in zip(strips, self.strips, seats, strict=True):
            self.controllers.append(build_strip(strip_config, strip, env, config.aliases, seat))
        self.meter_points: list[MeterPoint] = [config.meter_point(strip, layout) for strip in strips]
        """Where the meter of each strip of the configuration takes the level."""
        self.flow = Flow(
            self.strips,
            surface.strips,
            [collapses(strip) for strip in strips],
            lambda index: self.controllers[index].title,
            config.behavior.collapse_hold,
            clock,
            lambda device_index, index: self.desk.bind(
                device_index,
                self.controllers[index] if index is not None else None,
                self.meter_points[index] if index is not None else "pre_fader",
            ),
        )
        self.desk.on_hands_free = self._hands_free
        self.auto_strips = [controller for controller in self.controllers if isinstance(controller, AutoStrip)]
        self.claimed = tuple(
            controller.patterns for controller in self.controllers if isinstance(controller, AppGroupStrip)
        )
        self.assigner = AutoAssigner(len(self.auto_strips), config.behavior.auto_hold, config.behavior.ignore, clock)
        for index, auto in enumerate(self.auto_strips):
            auto.slot = AutoSlot(self.assigner, index, lambda: self.state, self.claimed, self.refresh)
        self.watches_processes = any(controller.launches for controller in self.controllers)
        if self.watches_processes:
            self.processes = processes()
        self.entities = {
            entity: default for controller in self.controllers for entity, default in controller.entities.items()
        }
        """The entities of the strips in Home Assistant, for the MQTT bridge."""
        if bridge is not None:
            bridge.bind(self.entities)
        if voip is not None:
            voip.subscribe(self.refresh)

    def _voip_seats(
        self, strips: tuple[StripConfig, ...], views: list[VirtualStrip], env: StripEnv
    ) -> list[VoipSeat | None]:
        """
        Where each `voip` strip sits among those of the layout (None for the other strips). The strips with the same
        `launch` share one button, so Select on any of them starts it once.
        """
        voip = [strip for strip in strips if isinstance(strip, VoipStripConfig)]
        if not voip:
            return [None] * len(strips)
        assert self.voip is not None, "the configuration has no voip strips without [voip]"
        seats = VoipSeats(self.voip, [strip.person for strip in voip], self.refresh)
        buttons: dict[tuple[str, ...], LaunchButton | None] = {}
        result: list[VoipSeat | None] = []
        for strip, view in zip(strips, views, strict=True):
            if not isinstance(strip, VoipStripConfig):
                result.append(None)
                continue
            if strip.launch is not None and strip.launch not in buttons:
                buttons[strip.launch] = launch_button(strip, view, env)
            launch = buttons[strip.launch] if strip.launch is not None else None
            result.append(VoipSeat(seats, sum(seat is not None for seat in result), launch))
        return result

    @property
    def voip_names(self) -> tuple[str | None, ...]:
        """For each strip of the layout, the name of the participant it shows: None for nobody, or no `voip` strip."""
        return tuple(
            person.name
            if isinstance(controller, VoipStrip) and (person := controller.participant) is not None
            else None
            for controller in self.controllers
        )

    # -- input ----------------------------------------------------------------------------------------------------

    def on_state(self, state: AudioState) -> None:
        self.state = state
        self.refresh()

    def refresh(self) -> None:
        for strip, app in zip(self.auto_strips, self.assigner.assign(self.state, self.claimed), strict=True):
            strip.assign(app)
        for controller in self.controllers:
            controller.update(self.state)
        self._place()
        self._watch_meters()

    def _watch_meters(self) -> None:
        """The meters capture for the strips on the device."""
        self.desk.watch(self.state)

    def _place(self) -> bool:
        """Moves the strips if one collapsed or came back (not while a finger is on the device); True if they moved."""
        absent = [controller.absent(self.state) for controller in self.controllers] if self.state.connected else None
        return self.flow.update(absent, self.desk.busy)

    def _hands_free(self) -> None:
        if self._place():
            # what waited for the hand to let go
            self._watch_meters()

    def auto_apps(self) -> tuple[dict[int, str], frozenset[int]]:
        """The application of each `auto` strip on the device (by strip, from 0), and the strips pinned."""
        apps: dict[int, str] = {}
        pinned: set[int] = set()
        for slot, (auto, app) in enumerate(zip(self.auto_strips, self.assigner.assigned, strict=True)):
            position = self.flow.position(self.controllers.index(auto))
            if position is not None and app is not None:
                apps[position] = app
                if slot in self.assigner.pinned:
                    pinned.add(position)
        return apps, frozenset(pinned)

    def keep_auto_apps(self, apps: dict[int, str], pinned: frozenset[int]) -> None:
        """
        Gives the `auto` strips on the strips of the device that had one before the application they had (see
        `auto_apps()`), so a new mixer for another strip doesn't shuffle them.
        """
        for slot, auto in enumerate(self.auto_strips):
            position = self.flow.position(self.controllers.index(auto))
            if position in apps:
                self.assigner.assigned[slot] = apps[position]
                if position in pinned:
                    self.assigner.pinned.add(slot)

    @property
    def placement(self) -> Placement:
        """For each strip of the device, the place of the strip of the configuration it shows."""
        return self.flow.placement

    # -- running --------------------------------------------------------------------------------------------------

    async def run(self) -> None:
        """
        Announces the entities of the `homeassistant` strips, then lets `auto` strips go of applications that stopped
        long enough. A mixer with its own desk runs it too (the meters).
        """
        if self.bridge is not None:
            await self.bridge.set_entities(self.entities | self.shared_entities, keep=self.keep, preview=self.preview)
        if self._own_desk:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.desk.run())
                group.create_task(self._tick())
        else:
            await self._tick()

    async def _tick(self) -> None:
        ticks_per_auto = round(AUTO_INTERVAL / TICK)
        ticks_per_scan = round(PROCESS_INTERVAL / TICK)
        tick = 0
        while True:
            await asyncio.sleep(TICK)
            tick += 1
            if self.watches_processes and tick % ticks_per_scan == 0:
                # a launched application shows up, the LED of a launch that took too long stops flashing
                self.processes = self._scan_processes()
                self.refresh()
            elif self.auto_strips and tick % ticks_per_auto == 0:
                self.refresh()
            elif self._place():
                # a strip collapsed after its hold time
                self._watch_meters()

    def close(self) -> None:
        self.desk.unbind(self.controllers)
        if self.desk.on_hands_free == self._hands_free:
            self.desk.on_hands_free = lambda: None
        if self.voip is not None:
            self.voip.unsubscribe(self.refresh)
        for controller in self.controllers:
            controller.close()
        if self._own_desk:
            self.desk.close()
        for strip in self.strips:
            # the next mixer draws on the device
            strip.target = None
