"""
The daemon: the surface, the sound server connection and the mixer of the current configuration, for as long as it
runs. SIGHUP (`systemctl --user reload xtouch-daemon`) loads the configuration again, SIGTERM/SIGINT stop it, and
it leaves the surface dark, so it is clear that nothing drives it anymore.

While the GUI asks for it (see `live.StartPreview`), the daemon runs the configuration of the GUI instead of the file,
in memory only, and goes back to the file when the GUI ends the preview, goes away or stops sending, or when the file
is loaded again.
"""

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, assert_never

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.select import MQTTSelect

from xtouch_daemon import __version__
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.media import MediaPlayers
from xtouch_daemon.audio.meter import PW_RECORD
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import default_config_path, load_config, parse_config
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.values import DEFAULT_LAYOUT
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.live.messages import (
    FEATURES,
    EndPreview,
    KeepPreview,
    MqttState,
    Reply,
    Request,
    SetMode,
    SetOverride,
    Snapshot,
    StartPreview,
    SwitchLayout,
    VoipState,
    fingerprint,
)
from xtouch_daemon.live.server import LiveServer, strip_states
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.binder import SlotMixer
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.runtime.homeassistant import SlotEntities
from xtouch_daemon.runtime.layouts import MANUAL, LayoutSwitcher, remember_layout, remembered_layout
from xtouch_daemon.runtime.mixer import Mixer
from xtouch_daemon.runtime.slots import BATCH as SLOTS_BATCH
from xtouch_daemon.runtime.slots import PROCESS_INTERVAL, SlotEngine
from xtouch_daemon.slots.states import Override
from xtouch_daemon.strips.homeassistant import entity_ids
from xtouch_daemon.system import instance, systemd
from xtouch_daemon.system.processes import running_processes
from xtouch_daemon.voip import VoipProvider, build_provider

_LOGGER = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 4.0
"""How long the faders may take to move down when the daemon stops (they go slowly, see FADER_SLOW_SMOOTH_TIME)."""
PREVIEW_TIMEOUT = 10.0
"""How long a preview runs without a request of its GUI (`live.KeepPreview`) before the daemon goes back to the file."""
PREVIEW_CHECK = 1.0
"""How often a running preview checks for its GUI and whether the configuration file changed."""
RULES_INTERVAL = 2.0
"""How often the rules of the layouts are checked for running processes, and for the end of their hold time."""
HOME_ASSISTANT = "Home Assistant"
"""The reason of a switch from Home Assistant."""
CHORD = "buttons"
"""The reason of a switch by the chord on the device."""


def layout_entity_ids(config: Config, namespace: str) -> frozenset[str]:
    """The unique ids of the entities in Home Assistant of the strips of every layout."""
    return frozenset(
        unique_id
        for name in config.layout_names
        for strip, strip_id in config.entity_strips(name)
        for unique_id in entity_ids(namespace, strip, strip_id)
    )


def mqtt_state(bridge: MqttBridge) -> MqttState:
    """The connection of the bridge, for the live view."""
    return MqttState(
        broker=f"{bridge.config.host}:{bridge.config.port}",
        username=bridge.config.username,
        connected=bridge.connected,
        ready=bridge.ready,
        error=bridge.error,
        entities=bridge.entity_count,
    )


def voip_state(provider: VoipProvider, strips: tuple[str | None, ...] = ()) -> VoipState:
    """The voice chat, for the live view; `strips` names who each strip of the layout shows (`Mixer.voip_names`)."""
    return VoipState(
        provider=provider.name,
        connected=provider.connected,
        client=provider.client,
        channel=provider.channel,
        participants=len(provider.participants),
        names=tuple(participant.name for participant in provider.participants),
        ids=tuple(participant.id for participant in provider.participants),
        strips=strips,
    )


def touchless(config: Config) -> frozenset[int]:
    """The strips (from 0) whose fader moves count without a touch: all of them without `touch_required`."""
    if not config.device.touch_required:
        return frozenset(range(protocol.STRIPS))
    return frozenset(number - 1 for number in config.device.touchless_faders)


class Daemon:
    def __init__(
        self,
        config: Config,
        backend: AudioBackend,
        surface: Surface | None = None,
        config_path: Path | None = None,
        capture_command: str = PW_RECORD,
        bridge: MqttBridge | None = None,
        live_socket: Path | None = None,
        players: MediaPlayers | None = None,
        voip_socket: Path | None = None,
        processes: Callable[[], frozenset[str]] = running_processes,
        layout_file: Path | None = None,
    ):
        """
        `bridge` is by default the one of the [mqtt] section, if there is one. `capture_command` is what the meters
        capture with. `live_socket` is where the live view
        for the GUI is served (see `live.server`), None for none. `players` are the media players of the session, for
        `encoder = "media"`. `voip_socket` is where the `bridge` VoIP provider waits for its plugin (by default
        `instance.voip_socket_file()`), `processes` tells the processes that run, for the rules of the layouts.
        `layout_file` is where the daemon keeps the layout it shows for the next start, unless a rule put it there
        (see `instance.layout_file()`), None for nowhere: it starts with that layout, and a rule that matches still
        switches to its own.
        """
        self.players = players
        self.config = config
        """The configuration that runs: the file's, or during a preview the GUI's."""
        self.file_config = config
        """The configuration of the file (the last one that could be used), to go back to after a preview."""
        self.config_path = config_path
        self._previewer: object | None = None
        """The client of the live view whose configuration runs (see `preview()`), None while the file's does."""
        self._preview_seen = 0.0
        """When the previewer sent its last request (the time of the event loop)."""
        self._watchdog: asyncio.Task[None] | None = None
        self._file_stamp = self._stamp()
        self.backend = backend
        self.surface = surface or Surface(config.device.name)
        self._configure_surface(config)
        self.bridge = bridge or (MqttBridge(config.mqtt) if config.mqtt is not None else None)
        if self.bridge is not None:
            self.bridge.on_connection = self._on_mqtt_connection
        self._voip_socket = voip_socket or instance.voip_socket_file()
        self._slots_wake = asyncio.Event()
        """Set when something the slots look at changed: they are resolved SLOTS_BATCH later."""
        self.voip = self._build_voip(config)
        self._voip_task: asyncio.Task[None] | None = None
        self._processes = processes
        self._layout_file = layout_file
        self._state_dir = layout_file.parent if layout_file is not None else None
        """Where the slots keep the choices and the people (see `runtime.slots`): next to the layout."""
        self.switcher = LayoutSwitcher(config, self._switched, active=self._remembered_layout(config))
        self.layout_select = self._layout_select(config)
        self.desk = Desk(self.surface, self._chord(config), self._on_chord, capture_command)
        """The strips of the device and the hands on them, for every mixer."""
        self.slots = self._slot_engine(config) if config.slots is not None else None
        """The slots of a configuration of channels, states and slots; None for one of strips and layouts."""
        self.desk.hands_free.append(self._wake_slots)
        self._slot_processes: tuple[float, frozenset[str]] | None = None
        """When the processes were scanned for the states of the slots last, and what ran."""
        self.slot_entities: SlotEntities | None = None
        """The states, the mode, the channels and the slots in Home Assistant (with slots and [mqtt])."""
        self.mixer = self._new_mixer()
        self._background: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()
        self._mixer_task: asyncio.Task[None] | None = None
        self.surface.on_connection = self._on_connection
        self.live = (
            LiveServer(live_socket, self.snapshot, self.on_request, self.on_client_closed)
            if live_socket is not None
            else None
        )

    @property
    def layout(self) -> str:
        """The layout the device shows."""
        return self.switcher.active

    def _new_mixer(self) -> Mixer | SlotMixer:
        shared: dict[MQTTEntity, str | None] = {}
        keep: frozenset[str] = frozenset()
        if self.bridge is not None:
            keep = layout_entity_ids(self.config, self.bridge.config.namespace)
            if self.layout_select is not None:
                shared[self.layout_select] = self.layout
        if self.slot_entities is not None:
            self.slot_entities.close()
            self.slot_entities = None
        if self.slots is not None and self.bridge is not None:
            assert self.config.slots is not None
            self.slot_entities = SlotEntities(self.bridge, self.slots, self.config.slots, self._wake_slots)
            shared |= self.slot_entities.entities
        if self.slots is not None:
            assert self.voip is not None, "people share the slots of auto in every configuration of slots"
            return SlotMixer(
                self.surface,
                self.backend,
                self.config,
                self.slots,
                self.desk,
                self.voip,
                bridge=self.bridge,
                players=self.players,
                shared_entities=shared,
                preview=self.previewing,
                processes=self._processes,
            )
        return Mixer(
            self.surface,
            self.backend,
            self.config,
            bridge=self.bridge,
            players=self.players,
            layout=self.layout,
            voip=self.voip,
            shared_entities=shared,
            keep=keep,
            preview=self.previewing,
            processes=self._processes,
            desk=self.desk,
        )

    def _remembered_layout(self, config: Config) -> str:
        """The layout of the last run, if it is still there (the default one otherwise)."""
        name = remembered_layout(self._layout_file) if self._layout_file is not None else None
        if name is None or name == DEFAULT_LAYOUT:
            return DEFAULT_LAYOUT
        if name not in config.layout_names:
            _LOGGER.info(
                f"The layout {name} of the last run is not in the configuration anymore, showing the default one"
            )
            return DEFAULT_LAYOUT
        _LOGGER.info(f"Showing the layout {name} of the last run")
        return name

    def _layout_select(self, config: Config) -> MQTTSelect | None:
        """`select.<ns>_layout` in Home Assistant, with the names of the layouts (with [mqtt] and layouts)."""
        if self.bridge is None or not config.layouts:
            return None
        select = MQTTSelect(
            self.bridge.config.namespace,
            "layout",
            "Layout",
            options=list(config.layout_names),
            icon="mdi:view-dashboard-variant",
            device=self.bridge.device,
        )
        self.bridge.watch(select, self._layout_state)
        self.bridge.watch_commands(select, self._layout_chosen)
        return select

    def _layout_chosen(self, name: str) -> None:
        """A choice in Home Assistant."""
        if name in self.switcher.names:
            self.switcher.switch(name, HOME_ASSISTANT)

    def _layout_state(self, entity: MQTTEntity) -> None:
        """
        Home Assistant shows the layout of the device: a state that says otherwise, e.g. the one retained from the last
        run (the daemon starts with the layout it remembers, or the one of a rule), is put right.
        """
        select = self.layout_select
        assert self.bridge is not None, "only with a bridge"
        if self.bridge.ready and select is not None and select.target_state != self.layout:
            self._in_background(select.set_state(self.layout), "mqtt layout")

    def _configure_surface(self, config: Config) -> None:
        """The options of the [device] section that apply without a restart."""
        self.surface.touchless = touchless(config)
        self.surface.startup, self.surface.shutdown = config.device.startup, config.device.shutdown

    # -- control --------------------------------------------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    def reload(self) -> bool:
        """
        Loads the configuration again. A configuration with errors is reported and the current one kept. A preview
        ends: the file runs again (the one before, if the file can't be used).
        """
        systemd.reloading()
        # also for a file with errors: the watch of a preview loads a changed file once
        self._file_stamp = self._stamp()
        try:
            config = load_config(self.config_path)
        except ConfigError as e:
            _LOGGER.error(f"Keeping the current configuration: {e}")
            self._back_to_file("the configuration file has errors, the device runs the one before")
            systemd.notify("READY=1", "STATUS=Configuration has errors, see the log")
            return False
        if config.mqtt != self.config.mqtt:
            # the connection and the entities of the strips depend on it
            _LOGGER.error("Keeping the current configuration: the [mqtt] section changed, restart the daemon instead")
            self._back_to_file("the [mqtt] section of the file changed, the device runs the file before")
            systemd.notify("READY=1", "STATUS=The [mqtt] section changed, restart the daemon")
            return False
        if config.device.name != self.config.device.name:
            _LOGGER.warning("The name in the [device] section changed: restart the daemon for it to take effect")
        self.file_config = config
        self._end_preview("the configuration file was loaded")
        self._use(config)
        _LOGGER.info("Configuration loaded again")
        systemd.notify("READY=1", self._status())
        return True

    def _use(self, config: Config) -> None:
        """
        Runs `config` (the file's, or a preview while one runs): its [device] options, VoIP provider and layouts, and
        a new mixer on the same surface, sound server and broker. The layout shown stays, if `config` has it.
        """
        self._configure_surface(config)
        self.desk.chord = self._chord(config)
        if config.voip != self.config.voip:
            self._replace_voip(config)
        if self.bridge is not None and self.layout_select is not None:
            self.bridge.unwatch(self.layout_select)
        self.config = config
        self.switcher = LayoutSwitcher(config, self._switched, active=self.switcher.active)
        self.layout_select = self._layout_select(config)
        if config.slots is None:
            self.slots = None
        elif self.slots is None:
            self.slots = self._slot_engine(config)
        else:
            # what the states, channels and members were carries over
            self.slots.reconfigure(config)
        self._replace_mixer()
        if self.slots is not None and self.mixer.state.connected:
            # the slots of the new configuration right away, not dark until the next step
            self._step_slots()

    def _replace_mixer(self) -> None:
        """A new mixer for the configuration and the layout, on the same surface, sound server and broker."""
        state = self.mixer.state
        self.mixer.close()
        self.mixer = self._new_mixer()
        # the sound server reports again only once something changes
        self.mixer.on_state(state)
        self._start_mixer()

    def _replace_voip(self, config: Config) -> None:
        if self._voip_task is not None:
            self._voip_task.cancel()
            self._voip_task = None
        self.voip = self._build_voip(config)
        self._start_voip()

    def _slot_engine(self, config: Config) -> SlotEngine:
        engine = SlotEngine(config, self._state_dir)
        # what the encoder of a slot picks shows at once
        engine.on_request = self._step_slots
        return engine

    def _build_voip(self, config: Config) -> VoipProvider | None:
        if config.voip is None:
            return None
        provider = build_provider(config.voip, self._voip_socket)
        provider.subscribe(self._wake_slots)
        return provider

    def _wake_slots(self) -> None:
        """Something the slots look at changed (the audio, the voice chat, a finger let go)."""
        self._slots_wake.set()

    def _start_voip(self) -> None:
        if self.voip is not None and self._mixer_task is not None:
            self._voip_task = asyncio.create_task(self.voip.run(), name=f"voip {self.voip.name}")

    def _stamp(self) -> tuple[int, int] | None:
        """When the configuration file changed last, and its size; None without a file."""
        try:
            stat = (self.config_path or default_config_path()).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    # -- layouts --------------------------------------------------------------------------------------------------

    def switch_layout(self, name: str, reason: str = MANUAL) -> bool:
        """Shows another layout (KeyError for one that is not there); False if it is the active one already."""
        return self.switcher.switch(name, reason)

    def _switched(self, name: str, reason: str) -> None:
        """Carries out a switch: the strips of the layout, its name on the LCDs, and the select in Home Assistant."""
        self._replace_mixer()
        seconds = self.config.switching.banner
        if seconds > 0:
            self.surface.banner(self.config.layout(name).title, reason, seconds)
        if self.layout_select is not None and self.layout_select.target_state != name:
            self._in_background(self.layout_select.set_state(name), "mqtt layout")
        if self._layout_file is not None and not self.switcher.by_rule:
            remember_layout(self._layout_file, name)

    def request_layout(self, name: str) -> Reply:
        """
        A switch asked for by a client of the live view (`live.SwitchLayout`): to the layout `name`, or with "+1"
        ("-1") to the next (previous) one.
        """
        if self.slots is not None:
            return self.request_mode(name)
        if name in ("+1", "-1"):
            self.switcher.step(int(name))
        elif name in self.switcher.names:
            self.switcher.switch(name)
        else:
            return Reply("layout", False, f"There is no layout {name} ({', '.join(self.switcher.names)})")
        return Reply("layout", True, self.layout)

    def request_mode(self, name: str, reason: str = MANUAL) -> Reply:
        """
        With slots, a layout asked for is a mode: `default` or a mode picks it (until the rules want another one),
        "+1" ("-1") the next (previous) one, `auto` lets the rules decide.
        """
        assert self.slots is not None
        modes = self.slots.modes
        if name in ("+1", "-1"):
            name = modes[(modes.index(self.slots.mode) + int(name)) % len(modes)]
        elif name != "auto" and name not in modes:
            return Reply("layout", False, f"There is no mode {name} (auto, {', '.join(modes)})")
        _LOGGER.info(f"Mode {name} ({reason})")
        self.slots.pick_mode(None if name == "auto" else name)
        self._step_slots()
        return Reply("layout", True, self.slots.mode)

    def request_override(self, name: str, value: str) -> Reply:
        """With slots: the override of a state that is no mode (`auto`, `on`, `off`)."""
        if self.slots is None:
            return Reply("override", False, "The configuration has no states (it has layouts)")
        states = [state for state, config in self.slots.scene.states.items() if not config.mode]
        if name not in states:
            return Reply("override", False, f"There is no state {name} ({', '.join(states) or 'none'})")
        if value not in Override:
            return Reply("override", False, f"{value} is no override (auto, on, off)")
        _LOGGER.info(f"State {name}: override {value} ({MANUAL})")
        self.slots.set_override(name, Override(value))
        self._step_slots()
        return Reply("override", True, value)

    @staticmethod
    def _chord(config: Config) -> frozenset[int]:
        """The strips (from 0) whose Solo buttons together switch the layout or mode."""
        return frozenset(number - 1 for number in config.switching.chord)

    def _on_chord(self) -> None:
        if self.slots is not None:
            action = self.config.switching.chord_action
            if action == "cycle_modes":
                self.request_mode("+1", CHORD)
            elif action.startswith("mode:"):
                self.request_mode(action.removeprefix("mode:"), CHORD)
            else:
                self.slots.toggle(action.removeprefix("toggle:"))
        else:
            self.switcher.step(1, CHORD)

    async def _follow_rules(self) -> None:
        """Checks the rules of the layouts for processes and for the end of their hold time, while there are any."""
        while True:
            await asyncio.sleep(RULES_INTERVAL)
            if self.switcher.has_rules:
                self.switcher.evaluate(self.mixer.state, self._running())

    async def _follow_slots(self) -> None:
        """
        Resolves the slots, while the configuration has them: SLOTS_BATCH after a change (what comes together goes
        together), when a delay or a dwell ends, and every PROCESS_INTERVAL for the processes.
        """
        while True:
            timeout = PROCESS_INTERVAL
            if self.slots is not None and (deadline := self.slots.deadline()) is not None:
                timeout = min(timeout, max(0.0, deadline - time.monotonic()))
            with contextlib.suppress(TimeoutError):
                # at least a moment: a deadline that is due must not keep the others from their turn
                await asyncio.wait_for(self._slots_wake.wait(), max(timeout, 0.001))
            if self._slots_wake.is_set():
                await asyncio.sleep(SLOTS_BATCH)
                self._slots_wake.clear()
            if self.slots is not None and self.mixer.state.connected:
                self._step_slots()

    def _step_slots(self) -> None:
        """One step of the slots: the slots that changed show their new controllers, the banner if the mode did."""
        assert self.slots is not None
        now = time.monotonic()
        if self._slot_processes is None or now - self._slot_processes[0] >= PROCESS_INTERVAL:
            self._slot_processes = (now, self._processes())
        mode = self.slots.mode if self.slots.simulation.states is not None else None
        held = self.desk.held_slots()
        voip = voip_state(self.voip) if self.voip is not None else None
        result = self.slots.step(self.mixer.state, self._slot_processes[1], voip, held, now)
        states = self.slots.simulation.states
        assert states is not None
        seconds = self.config.switching.banner
        new_mode = mode is not None and states.mode != mode
        assert isinstance(self.mixer, SlotMixer)
        # a new mode shows its banner instead of a flash per slot
        self.mixer.apply(result, 0.0 if new_mode else seconds)
        self.mixer.refresh()
        if self.slot_entities is not None:
            self.slot_entities.update(result)
        if new_mode and seconds > 0:
            self.surface.banner(self.slots.mode_label(states.mode), states.reasons.get(states.mode, ""), seconds)

    def _running(self) -> frozenset[str]:
        return self._processes() if self.switcher.watches_processes else frozenset()

    # -- the live view: the preview of the GUI, and layout switches -----------------------------------------------

    @property
    def previewing(self) -> bool:
        """Whether a configuration of the GUI runs instead of the file."""
        return self._previewer is not None

    def on_request(self, client: object, request: Request) -> Reply | None:
        """A request of a client of the live view (the user's own, `LiveServer` checks that)."""
        match request:
            case StartPreview(config=text):
                return self.preview(client, text)
            case KeepPreview():
                if client is self._previewer:
                    self._preview_seen = asyncio.get_running_loop().time()
                return None
            case EndPreview():
                if client is self._previewer:
                    self._back_to_file("the GUI ended it")
                return None
            case SwitchLayout(layout=name):
                return self.request_layout(name)
            case SetMode(mode=name):
                if self.slots is None:
                    return Reply("mode", False, "The configuration has no modes (it has layouts)")
                reply = self.request_mode(name)
                return Reply("mode", reply.ok, reply.message)
            case SetOverride(state=name, value=value):
                return self.request_override(name, value)
            case _ as unreachable:
                assert_never(unreachable)

    def on_client_closed(self, client: object) -> None:
        """A client of the live view went away; if it previewed (the GUI was closed or crashed), the file runs again."""
        if client is self._previewer:
            self._back_to_file("the GUI went away")

    def preview(self, client: object, text: str) -> Reply:
        """
        Runs the configuration `text` (TOML) of `client` instead of the file, like a reload but without the file,
        which is never written. One with errors is not used: the reply tells them, and what runs keeps running. A
        second client takes the preview over, and the first one is told.
        """
        try:
            config = parse_config(text, "The previewed configuration")
        except ConfigError as e:
            return Reply("preview", False, str(e))
        if config.mqtt != self.config.mqtt:
            return Reply(
                "preview",
                False,
                "A preview can't change the [mqtt] section: save it and restart the daemon, or undo the change.",
            )
        previous = self._previewer
        if previous is not None and previous is not client and self.live is not None:
            self.live.tell(previous, Reply("ended", True, "another window previews now"))
        self._previewer = client
        self._preview_seen = asyncio.get_running_loop().time()
        if previous is None:
            _LOGGER.info("Previewing a configuration of the GUI, the file stays as it is")
            self._watchdog = asyncio.create_task(self._watch_preview(), name="preview watch")
        changed = fingerprint(config) != fingerprint(self.config)
        if previous is None or changed:
            _LOGGER.debug("Running the previewed configuration")
            self._use(config)
        if previous is None:
            systemd.notify(self._status())
        if config.device.name != self.file_config.device.name:
            return Reply("preview", True, "The device name changes only with a restart.")
        return Reply("preview", True)

    def _end_preview(self, reason: str) -> bool:
        """Ends the preview (the previewer is told why) without changing what runs; False when none ran."""
        previewer = self._previewer
        if previewer is None:
            return False
        self._previewer = None
        watchdog, self._watchdog = self._watchdog, None
        if watchdog is not None and watchdog is not asyncio.current_task():
            watchdog.cancel()
        if self.live is not None:
            self.live.tell(previewer, Reply("ended", True, reason))
        _LOGGER.info(f"The preview ended, {reason}")
        return True

    def _back_to_file(self, reason: str) -> None:
        """Ends the preview, if one runs, and runs the configuration of the file again."""
        if self._end_preview(reason):
            self._use(self.file_config)
            systemd.notify(self._status())

    async def _watch_preview(self) -> None:
        """Goes back to the file when the GUI stops sending (e.g. it hangs), and loads the file once it changed."""
        while True:
            await asyncio.sleep(PREVIEW_CHECK)
            if self._stamp() != self._file_stamp:
                _LOGGER.info("The configuration file changed during the preview, loading it")
                self.reload()
                return
            if asyncio.get_running_loop().time() - self._preview_seen > PREVIEW_TIMEOUT:
                self._back_to_file(f"no word from the GUI for {PREVIEW_TIMEOUT:.0f} s")
                return

    # -- running --------------------------------------------------------------------------------------------------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        handlers = {signal.SIGTERM: self.stop, signal.SIGINT: self.stop, signal.SIGHUP: self.reload}
        for signum, handler in handlers.items():
            loop.add_signal_handler(signum, handler)
        surface = asyncio.create_task(self.surface.run(), name="surface")
        parts = [
            asyncio.create_task(self.backend.run(self._on_state), name="sound server"),
            asyncio.create_task(self.desk.run(), name="meters"),
        ]
        if self.bridge is not None:
            parts.append(asyncio.create_task(self.bridge.run(), name="mqtt"))
        self._start_mixer()
        self._start_voip()
        self._in_background(self._follow_rules(), "layout rules")
        self._in_background(self._follow_slots(), "slots")
        if self.live is not None:
            # not one of the parts: the daemon works without it
            self._in_background(self.live.run(), "live view")
        if self.players is not None:
            self._in_background(self.players.run(), "media players")
        systemd.notify("READY=1", self._status())
        layouts = f" ({len(self.config.layout_names)} layouts)" if self.config.layouts else ""
        shows = (
            f"{len(self.mixer.controllers)} strips{layouts}"
            if self.config.slots is None
            else f"{len(self.config.slots.channels)} channels"
        )
        _LOGGER.info(f"Running with {shows}, waiting for {self.config.device.name}")
        stopped = asyncio.create_task(self._stop.wait())
        try:
            done, _ = await asyncio.wait([stopped, surface, *parts], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopped:
                    # a part of the daemon ended, which they never do on their own
                    task.result()
        finally:
            systemd.notify("STOPPING=1")
            stopped.cancel()
            # another signal (a second Ctrl+C, or one that `uv run` passes on) must not cut the shutdown short: the
            # faders would stop half way down
            for signum in handlers:
                loop.add_signal_handler(signum, self._stopping_already)
            try:
                await self._shutdown(surface, parts)
            finally:
                for signum in handlers:
                    loop.remove_signal_handler(signum)

    def _stopping_already(self) -> None:
        _LOGGER.info("Stopping already, the faders are on their way down")

    async def _shutdown(self, surface: asyncio.Task[None], parts: list[asyncio.Task[None]]) -> None:
        """
        Leaves the surface dark: first everything stops that could show something on it (the sound server, Home
        Assistant, the mixer, the device's own events), then the shutdown sequence puts the strips away, and only then
        the surface closes.
        """
        _LOGGER.info("Stopping")
        self.surface.on_event = lambda event: None
        self.mixer.close()
        self.desk.close()
        if self.bridge is not None:
            # while it is still connected: Home Assistant sees the entities unavailable right away
            await self.bridge.close()
        assert self._mixer_task is not None, "run() starts the mixer"
        others = [*parts, self._mixer_task, *self._background, *([self._voip_task] if self._voip_task else [])]
        if self._watchdog is not None:
            others.append(self._watchdog)
        for task in others:
            task.cancel()
        await asyncio.gather(*others, return_exceptions=True)
        await self.desk.wait_closed()

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.surface.put_away(), SHUTDOWN_TIMEOUT)

        # its end sends what is still queued and closes the device
        surface.cancel()
        await asyncio.gather(surface, return_exceptions=True)

    def _start_mixer(self) -> None:
        if self._mixer_task is not None:
            self._mixer_task.cancel()
        self._mixer_task = asyncio.create_task(self.mixer.run(), name="mixer")

    def _on_state(self, state: AudioState) -> None:
        was_connected = self.mixer.state.connected
        self.mixer.on_state(state)
        self._wake_slots()
        if state.connected != was_connected:
            systemd.notify(self._status())
        if self.switcher.has_rules and state.connected:
            self.switcher.evaluate(state, self._running())

    def _on_connection(self, connected: bool) -> None:
        # the surface shows everything again by itself after a connect
        systemd.notify(self._status())
        if self.bridge is not None:
            # Home Assistant greys out the entities of a device that is not there
            self._in_background(self.bridge.set_available(connected), "mqtt availability")

    def _on_mqtt_connection(self, connected: bool) -> None:
        self.mixer.refresh()
        if not connected and self.slot_entities is not None:
            self.slot_entities.forget()
        systemd.notify(self._status())

    def _in_background(self, coroutine: Coroutine[Any, Any, None], name: str) -> None:
        task = asyncio.create_task(coroutine, name=name)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def snapshot(self) -> Snapshot:
        """What the daemon and the device do right now, for the live view of the GUI."""
        return Snapshot(
            config=fingerprint(self.config),
            device=self.surface.connected,
            sound_server=self.mixer.state.connected,
            mqtt=None if self.bridge is None else self.bridge.connected,
            strips=strip_states(self.surface, time.monotonic()),
            mqtt_state=None if self.bridge is None else mqtt_state(self.bridge),
            daemon_version=__version__,
            preview=self.previewing,
            features=FEATURES,
            layout=self.layout if self.slots is None else self.slots.mode,
            # with slots: the modes, and auto to give the choice back to the rules
            layouts=self.switcher.names if self.slots is None else (*self.slots.modes, "auto"),
            voip=None if self.voip is None else voip_state(self.voip, self.mixer.voip_names),
            placement=self.mixer.placement,
            slots=self.slots.view() if self.slots is not None else None,
        )

    def _status(self) -> str:
        device = self.config.device.name
        surface = f"{device} connected" if self.surface.connected else f"waiting for {device}"
        sound = "sound server connected" if self.mixer.state.connected else "waiting for the sound server"
        mqtt = ""
        if self.bridge is not None:
            mqtt = ", MQTT connected" if self.bridge.connected else ", waiting for MQTT"
        preview = ", previewing unsaved changes of the GUI" if self.previewing else ""
        return f"STATUS={surface}, {sound}{mqtt}{preview}"
