"""
The daemon: the surface, the sound server connection and the slots of the current configuration, for as long as it
runs. SIGHUP (`systemctl --user reload xtouch-daemon`) loads the configuration again, SIGTERM/SIGINT stop it, and
it leaves the surface dark, so it is clear that nothing drives it anymore.

While the GUI asks for it (see `live.StartPreview`), the daemon runs the configuration of the GUI instead of the file,
in memory only, and goes back to the file when the GUI ends the preview, goes away or stops sending, or when the file
is loaded again.
"""

import asyncio
import contextlib
import dataclasses
import logging
import signal
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, assert_never

from haad_mqtt_autodiscovery.entity import MQTTEntity

from xtouch_daemon import __version__
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.media import MediaPlayers
from xtouch_daemon.audio.meter import PW_RECORD
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import default_config_path, load_config, parse_config
from xtouch_daemon.config.model import Config
from xtouch_daemon.hardware.protocol import StripEvent
from xtouch_daemon.hardware.selftest import TestBench, sweep
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.hardware.transport import AlsaPort, Port, SocketPort
from xtouch_daemon.live.log import LogBuffer
from xtouch_daemon.live.messages import (
    FEATURES,
    DaemonRequest,
    EndPreview,
    EndTest,
    ForgetDevice,
    KeepPreview,
    KeepTest,
    MqttState,
    Play,
    Reply,
    SetMode,
    SetOverride,
    Snapshot,
    StartPreview,
    StartTest,
    TwinView,
    fingerprint,
    steady,
)
from xtouch_daemon.live.server import LiveServer, strip_states, voip_state
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.binder import SlotMixer
from xtouch_daemon.runtime.device_memory import DEVICES_FILE_NAME, DeviceMemory
from xtouch_daemon.runtime.homeassistant import SlotEntities
from xtouch_daemon.runtime.rig import Rig
from xtouch_daemon.runtime.slots import PROCESS_INTERVAL
from xtouch_daemon.runtime.twin import Twin
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.slots.outcomes import Situation
from xtouch_daemon.slots.recording import Observer
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.slots.world import Names
from xtouch_daemon.system import instance, systemd
from xtouch_daemon.system.commands import Commands
from xtouch_daemon.system.processes import running_processes
from xtouch_daemon.voip import VoipProvider, build_provider

_LOGGER = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 4.0
"""How long the faders may take to move down when the daemon stops (they go slowly, see FADER_SLOW_SMOOTH_TIME)."""
PREVIEW_TIMEOUT = 10.0
"""How long a preview runs without a request of its GUI (`live.KeepPreview`) before the daemon goes back to the file."""
PREVIEW_CHECK = 1.0
"""How often a running preview checks for its GUI and whether the configuration file changed."""
TEST_TIMEOUT = 10.0
"""How long the test of the device runs without a request of its client (`live.KeepTest`)."""
DEVICE_CHECK = 2.0
"""How often the daemon looks for the device of `[device] name` while it drives the virtual one (`device_plugged`)."""
FILE_CHECK = 1.0
"""
How often the daemon looks at the configuration file (its time and size). A change is loaded once the file looked the
same twice: an editor writes it in steps.
"""


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


def device_port(name: str, virtual: bool) -> Port:
    """How to reach the device named `name`, or the virtual device (`[device] virtual`)."""
    return SocketPort(instance.virtual_device_socket_file()) if virtual else AlsaPort(name)


def device_surface(name: str, virtual: bool) -> Surface:
    """The surface of the device named `name`, or of the virtual device (`[device] virtual`)."""
    return Surface(port=device_port(name, virtual))


@dataclass
class TwinSession:
    """The virtual twin of a client of the live view."""

    twin: Twin
    task: asyncio.Task[None]
    seen: float
    """When the client sent its last request for it (the time of the event loop)."""
    last: TwinView | None = None
    """What the client was sent last, `steady()`: a view that tells nothing else is not sent."""
    due: bool = False
    """Whether a view goes out once the event loop is through with what it does now."""


class Daemon(Rig):
    """
    The rig of the device (see `runtime.rig`), with the configuration file, Home Assistant, the live view of the GUI,
    its previews and its virtual twins.
    """

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
        state_dir: Path | None = None,
        log: LogBuffer | None = None,
        commands: Commands | None = None,
    ):
        """
        `bridge` is by default the one of the [mqtt] section, if there is one. `capture_command` is what the meters
        capture with. `live_socket` is where the live view
        for the GUI is served (see `live.server`), None for none. `players` are the media players of the session, for
        `encoder = "media"`. `voip_socket` is where the `bridge` VoIP provider waits for its plugin (by default
        `instance.voip_socket_file()`), `processes` tells the processes that run, for the states. `state_dir` is where
        the slots keep the overrides, the mode picked by hand and the order of the people for the next start (see
        `instance.state_dir()`), None for nowhere. `log` keeps the records of the log for the GUI (`live.WatchLog`).
        `commands` runs the programs of command channels.
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
        self._tester: object | None = None
        """The client of the live view whose test of the device runs (see `start_test()`), None while none does."""
        self._test_seen = 0.0
        """When the tester sent its last request (the time of the event loop)."""
        self._test: asyncio.Task[None] | None = None
        """Runs the test: the sweep, then the bench until the tester is gone."""
        self._bench: TestBench | None = None
        """The strips answering their controls, after the sweep."""
        self._twins: dict[object, TwinSession] = {}
        """The virtual twins (see `runtime.twin`), by the client of the live view that asked for them."""
        self._closing: set[asyncio.Task[None]] = set()
        """The twins that ended and are stopping (see `_close_twin()`): the shutdown waits for them."""
        self._file_stamp = self._stamp()
        self.device_plugged = False
        """Whether the device of `[device] name` is plugged in while the daemon drives the virtual one."""
        self.bridge = bridge or (MqttBridge(config.mqtt) if config.mqtt is not None else None)
        if self.bridge is not None:
            self.bridge.on_connection = self._on_mqtt_connection
            self.bridge.on_change = self._changed
        self._voip_socket = voip_socket or instance.voip_socket_file()
        self._voip_task: asyncio.Task[None] | None = None
        self._device_switch: asyncio.Task[None] | None = None
        """Lets go of the device for another one (a reload with another `[device] name` or `virtual`)."""
        self._scan_processes = processes
        self._slot_processes: tuple[float, frozenset[str]] | None = None
        """When the processes were scanned for the states of the slots last, and what ran."""
        self.slot_entities: SlotEntities | None = None
        """The states, the mode, the channels and the slots in Home Assistant (with slots and [mqtt])."""
        self.devices_seen = DeviceMemory(state_dir / DEVICES_FILE_NAME if state_dir is not None else None)
        """The devices the sound server had, for the suggestions of the GUI (see `runtime.device_memory`)."""
        super().__init__(
            config,
            surface or device_surface(config.device.name, config.device.virtual),
            backend,
            self._build_voip(config),
            state_dir=state_dir,
            capture_command=capture_command,
            commands=commands if commands is not None else Commands(),
        )
        self._background: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()
        self._stopping = False
        """Whether the daemon stops: the live view still shows the shutdown sequence, but takes no more requests."""
        self._live_task: asyncio.Task[None] | None = None
        self._mixer_task: asyncio.Task[None] | None = None
        self.surface.on_connection = self._on_connection
        self.surface.on_change = self._changed
        self.live = (
            LiveServer(live_socket, self.snapshot, self.on_request, self.on_client_closed, self.devices_seen.known, log)
            if live_socket is not None
            else None
        )

    def _new_mixer(self) -> SlotMixer:
        shared: dict[MQTTEntity, str | None] = {}
        if self.slot_entities is not None:
            self.slot_entities.close()
            self.slot_entities = None
        if self.bridge is not None:
            self.slot_entities = SlotEntities(self.bridge, self.slots, self.config.slots, self.wake_slots)
            shared |= self.slot_entities.entities
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
            processes=self._scan_processes,
            commands=self.commands,
            on_presence=self.wake_slots,
        )

    def _configure_surface(self, config: Config) -> None:
        super()._configure_surface(config)
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
        if (config.device.name, config.device.virtual) != (self.config.device.name, self.config.device.virtual):
            # another device: the strips show the same on it once it is connected
            port = device_port(config.device.name, config.device.virtual)
            self._device_switch = asyncio.create_task(self.surface.use(port), name="device switch")
        self.file_config = config
        self._end_preview("the configuration file was loaded")
        self._use(config)
        _LOGGER.info("Configuration loaded again")
        systemd.notify("READY=1", self._status())
        return True

    def _use(self, config: Config) -> None:
        """
        Runs `config` (the file's, or a preview while one runs): its VoIP provider, then like `reconfigure()`, on the
        same broker too.
        """
        if config.voip != self.config.voip:
            self._replace_voip(config)
        self.reconfigure(config)
        self._changed()

    def _replace_mixer(self) -> None:
        super()._replace_mixer()
        if self._mixer_task is not None:
            # it runs with the daemon: run() starts it otherwise
            self._start_mixer()

    def _replace_voip(self, config: Config) -> None:
        if self._voip_task is not None:
            self._voip_task.cancel()
            self._voip_task = None
        self.voip = self._build_voip(config)
        self._start_voip()

    def _build_voip(self, config: Config) -> VoipProvider:
        assert config.voip is not None, "people share the slots of auto in every configuration"
        provider = build_provider(config.voip, self._voip_socket)
        provider.subscribe(self.wake_slots)
        provider.subscribe(self._reality_changed)
        return provider

    def _start_voip(self) -> None:
        if self._mixer_task is not None:
            self._voip_task = asyncio.create_task(self.voip.run(), name=f"voip {self.voip.name}")

    def _stamp(self) -> tuple[int, int] | None:
        """When the configuration file changed last, and its size; None without a file."""
        try:
            stat = (self.config_path or default_config_path()).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    # -- the slots of the device -------------------------------------------------------------------------------------

    def _processes(self, now: float) -> frozenset[str]:
        """Scanned every PROCESS_INTERVAL at most (`/proc` is not free)."""
        if self._slot_processes is None or now - self._slot_processes[0] >= PROCESS_INTERVAL:
            self._slot_processes = (now, self._scan_processes())
        return self._slot_processes[1]

    def _stepped(self, result: Result) -> None:
        if self.slot_entities is not None and self.slots.situation is None:
            # Home Assistant never sees a situation the GUI tries
            self.slot_entities.update(result)
        self._reality_changed()

    # -- the live view: the preview of the GUI, modes and overrides ---------------------------------------------------

    @property
    def previewing(self) -> bool:
        """Whether a configuration of the GUI runs instead of the file."""
        return self._previewer is not None

    def on_request(self, client: object, request: DaemonRequest) -> Reply | None:
        """A request of a client of the live view (the user's own, `LiveServer` checks that)."""
        try:
            return self._answer(client, request)
        finally:
            # a preview, a mode, an override: the snapshot tells it
            self._changed()

    def _answer(self, client: object, request: DaemonRequest) -> Reply | None:
        if self._stopping:
            return _refused(request)
        match request:
            case StartPreview(config=text, situation=situation, on_device=True):
                return self.preview(client, text, situation)
            case StartPreview(config=text, situation=situation):
                return self.preview_on_twin(client, text, situation)
            case KeepPreview():
                now = asyncio.get_running_loop().time()
                if client is self._previewer:
                    self._preview_seen = now
                if (session := self._twins.get(client)) is not None:
                    session.seen = now
                return None
            case EndPreview():
                self._end_twin(client, None)
                if client is self._previewer:
                    self._back_to_file("the GUI ended it")
                return None
            case SetMode(mode=name):
                return self.request_mode(name)
            case SetOverride(state=name, value=value):
                return self.request_override(name, value)
            case Play(event=event, preview=True):
                if (session := self._twins.get(client)) is not None:
                    session.twin.play(event)
                return None
            case Play(event=event):
                self.surface.play(event)
                return None
            case StartTest():
                return self.start_test(client)
            case KeepTest():
                if client is self._tester:
                    self._test_seen = asyncio.get_running_loop().time()
                return None
            case EndTest():
                if client is self._tester:
                    self.end_test("the GUI ended it", tell=False)
                return None
            case ForgetDevice(name=name, direction=direction):
                if self.devices_seen.forget(name, direction) and self.live is not None:
                    self.live.publish_known()
                return None
            case _ as unreachable:
                assert_never(unreachable)

    def on_client_closed(self, client: object) -> None:
        """
        A client of the live view went away; if it previewed (the GUI was closed or crashed), the file runs again, if it
        tested the device, the device shows the slots again.
        """
        self._end_twin(client, None)
        if client is self._tester:
            self.end_test("the GUI went away", tell=False)
        if client is self._previewer:
            self._back_to_file("the GUI went away")

    def preview(self, client: object, text: str | None, situation: Situation | None = None) -> Reply:
        """
        Runs the configuration `text` (TOML; None: the file's) of `client` instead of the file, like a reload but
        without the file, which is never written; with a `situation`, the slots show that situation instead of the
        real one (see `SlotEngine.simulate`). One with errors is not used: the reply tells them, and what runs keeps
        running. A second client takes the device over, and the first one is told. The twin of `client` ends: the
        preview is on the device now.
        """
        try:
            config = self.file_config if text is None else parse_config(text, "The previewed configuration")
        except ConfigError as e:
            return Reply("preview", False, str(e))
        if situation is not None and situation.mode not in (DEFAULT, *config.slots.scene.modes):
            return Reply("preview", False, f"No mode {situation.mode} in the configuration.")
        if config.mqtt != self.config.mqtt:
            return Reply(
                "preview",
                False,
                "A preview can't change the [mqtt] section: save it and restart the daemon, or undo the change.",
            )
        self._end_twin(client, None)
        self.end_test("a preview on the device took it")
        previous = self._previewer
        if previous is not None and previous is not client and self.live is not None:
            self.live.tell(previous, Reply("ended", True, "another window previews on the device now"))
        self._previewer = client
        self._preview_seen = asyncio.get_running_loop().time()
        if previous is None:
            _LOGGER.info("Previewing a configuration of the GUI, the file stays as it is")
            self._watchdog = asyncio.create_task(self._watch_preview(), name="preview watch")
        changed = fingerprint(config) != fingerprint(self.config)
        simulated = situation != self.slots.situation
        if simulated:
            _LOGGER.info(f"Showing the situation {situation} of the GUI" if situation else "Showing the real situation")
            self.slots.simulate(situation)
        if previous is None or changed:
            _LOGGER.debug("Running the previewed configuration")
            self._use(config)
        elif simulated and self.mixer.state.connected:
            self.step()
        if previous is None:
            systemd.notify(self._status())
        if (config.device.name, config.device.virtual) != (
            self.file_config.device.name,
            self.file_config.device.virtual,
        ):
            return Reply("preview", True, "The device name and virtual change when the file is saved.")
        return Reply("preview", True)

    # -- virtual twins ----------------------------------------------------------------------------------------------

    def _names(self) -> Names:
        """What is real right now, as plain strings, for the stand-ins of a twin."""
        return Names.of(Observer().observe(self.mixer.state, frozenset(), voip_state(self.voip), time.monotonic()))

    def _situation_now(self) -> Situation:
        """The mode and the states that are on in reality, for a twin of edits without a situation."""
        states = self.slots.simulation.states
        if states is None:
            return Situation()
        on = frozenset(name for name, value in states.values.items() if value and name not in self.slots.scene.modes)
        return Situation(states.mode, on)

    def preview_on_twin(self, client: object, text: str | None, situation: Situation | None) -> Reply:
        """
        Runs the configuration `text` (None: the file's) in `situation` on a twin of `client` (a new one, or the one
        it has: it follows), without a `situation` in the situation of now. One with errors is not used: the reply
        tells them, and the twin it had keeps running. If `client` had the device, the device runs the file again.
        """
        try:
            config = self.file_config if text is None else parse_config(text, "The previewed configuration")
        except ConfigError as e:
            return Reply("preview", False, str(e))
        if situation is not None and situation.mode not in (DEFAULT, *config.slots.scene.modes):
            return Reply("preview", False, f"No mode {situation.mode} in the configuration.")
        if client is self._previewer:
            # it asked for it: no news for it
            self._back_to_file("the preview went to the GUI", tell=False)
        real = situation is None
        situation = self._situation_now() if situation is None else situation
        now = asyncio.get_running_loop().time()
        session = self._twins.get(client)
        if session is None:
            twin = Twin(config, situation, self._names(), real=real)
            twin.on_change = lambda: self._twin_changed(client)
            task = asyncio.create_task(twin.run(), name="virtual twin")
            task.add_done_callback(lambda done: self._twin_stopped(client, done))
            self._twins[client] = TwinSession(twin, task, now)
            _LOGGER.debug("A virtual twin for a client of the live view")
            return Reply("preview", True)
        session.seen = now
        if fingerprint(config) != fingerprint(session.twin.config):
            session.twin.reconfigure(config)
        session.twin.set_situation(situation, real)
        return Reply("preview", True)

    def _end_twin(self, client: object, why: str | None) -> None:
        """Ends the twin of a client, if it has one; with a `why` the client is told."""
        session = self._twins.pop(client, None)
        if session is None:
            return
        closing = asyncio.create_task(self._close_twin(session), name="virtual twin closing")
        self._closing.add(closing)
        closing.add_done_callback(self._closing.discard)
        if why is not None and self.live is not None:
            self.live.tell(client, Reply("ended", True, why))
        _LOGGER.debug(f"A virtual twin ended: {why or 'the client asked, or went away'}")

    @staticmethod
    async def _close_twin(session: TwinSession) -> None:
        """Stops a twin and waits until its meters' signals and its task ended."""
        session.task.cancel()
        session.twin.close()
        await asyncio.gather(session.task, return_exceptions=True)
        await session.twin.wait_closed()

    def _twin_stopped(self, client: object, task: asyncio.Task[None]) -> None:
        """A twin's task ended: unless it was ended, it failed, and its client is told (the view would stand still)."""
        session = self._twins.get(client)
        if task.cancelled() or session is None or session.task is not task:
            return
        error = task.exception()
        _LOGGER.error("The virtual twin of a client of the live view stopped", exc_info=error)
        self._end_twin(client, f"the virtual twin failed: {error}" if error else "the virtual twin stopped")

    def _twin_changed(self, client: object) -> None:
        """What the twin of `client` shows may have changed: its view goes out once the event loop is through."""
        session = self._twins.get(client)
        if session is None or session.due:
            return
        session.due = True
        asyncio.get_running_loop().call_soon(self._send_view, client, session)

    def _send_view(self, client: object, session: TwinSession) -> None:
        session.due = False
        if self._twins.get(client) is not session or self.live is None:
            return
        view = session.twin.view()
        if view is None:
            return
        view_steady = dataclasses.replace(view, strips=steady(view.strips))
        if view_steady == session.last:
            return
        session.last = view_steady
        self.live.tell_view(client, view)

    def _reality_changed(self) -> None:
        """
        What is real changed (the sound server, the voice chat, a step of the slots): the snapshot tells it, and the
        twins follow its names, and its mode and states where they show edits without Simulate.
        """
        self._changed()
        if not self._twins:
            return
        names = self._names()
        situation = self._situation_now()
        for session in self._twins.values():
            session.twin.set_names(names)
            if session.twin.real:
                session.twin.set_situation(situation, real=True)

    async def _watch_twins(self) -> None:
        """Ends the twins that nobody keeps (no request of their client for PREVIEW_TIMEOUT)."""
        while True:
            await asyncio.sleep(PREVIEW_CHECK)
            now = asyncio.get_running_loop().time()
            for client, session in list(self._twins.items()):
                if now - session.seen > PREVIEW_TIMEOUT:
                    self._end_twin(client, f"no word from the GUI for {PREVIEW_TIMEOUT:.0f} s")

    def _end_preview(self, reason: str, tell: bool = True) -> bool:
        """Ends the preview (the previewer is told why) without changing what runs; False when none ran."""
        previewer = self._previewer
        if previewer is None:
            return False
        self._previewer = None
        # the real situation again: what runs next steps the real slots
        self.slots.simulate(None)
        watchdog, self._watchdog = self._watchdog, None
        if watchdog is not None and watchdog is not asyncio.current_task():
            watchdog.cancel()
        if tell and self.live is not None:
            self.live.tell(previewer, Reply("ended", True, reason))
        _LOGGER.info(f"The preview ended, {reason}")
        self._changed()
        return True

    def _back_to_file(self, reason: str, tell: bool = True) -> None:
        """Ends the preview, if one runs, and runs the configuration of the file again."""
        if self._end_preview(reason, tell):
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

    # -- the test of the device -----------------------------------------------------------------------------------

    @property
    def testing(self) -> bool:
        """Whether the device runs its test (see `start_test()`)."""
        return self._tester is not None

    def start_test(self, client: object) -> Reply:
        """
        Runs the test of the device for `client` (see `hardware.selftest`): the sweep, then every strip answers its
        controls. The slots go on, but nothing of theirs reaches the device until `end_test()`. A preview on the device
        ends; another client that runs the test takes it over, and the first one is told.
        """
        if not self.surface.connected:
            return Reply("test", False, "The device is not connected.")
        now = asyncio.get_running_loop().time()
        previous = self._tester
        self._tester = client
        self._test_seen = now
        if previous is not None:
            if previous is not client and self.live is not None:
                self.live.tell(previous, Reply("test_ended", True, "another window tests the device now"))
            return Reply("test", True)
        self._back_to_file("the device is tested now")
        strips = self.surface.lend()
        self.surface.on_event = self._test_event
        self._test = asyncio.create_task(self._run_test(strips), name="test of the device")
        _LOGGER.info("Testing the device: the slots go on, but don't show on it until the test ends")
        systemd.notify(self._status())
        return Reply("test", True)

    def end_test(self, reason: str, tell: bool = True) -> bool:
        """Ends the test, if one runs (`tell`: its client learns why): the device shows the slots again."""
        tester = self._tester
        if tester is None:
            return False
        self._tester = None
        task, self._test = self._test, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        bench, self._bench = self._bench, None
        if bench is not None:
            bench.close()
        self.surface.take_back()
        self.surface.on_event = self.desk.dispatch
        if tell and self.live is not None:
            self.live.tell(tester, Reply("test_ended", True, reason))
        _LOGGER.info(f"The test of the device ended, {reason}")
        systemd.notify(self._status())
        self._changed()
        return True

    async def _run_test(self, strips: list[Strip]) -> None:
        """The sweep, then the bench, until the tester sends nothing for TEST_TIMEOUT."""
        await sweep(self.surface, strips=strips)
        self._bench = TestBench(strips, lambda line: _LOGGER.info(f"Test: {line}"))
        self._bench.start()
        loop = asyncio.get_running_loop()
        # the time of the sweep doesn't count against the GUI
        self._test_seen = max(self._test_seen, loop.time())
        while True:
            await asyncio.sleep(PREVIEW_CHECK)
            if loop.time() - self._test_seen > TEST_TIMEOUT:
                self.end_test(f"no word from the GUI for {TEST_TIMEOUT:.0f} s")
                return

    def _test_event(self, event: StripEvent) -> None:
        """An input on the device while the test has it: the bench answers (nothing during the sweep)."""
        if self._bench is not None:
            self._bench.handle(event)

    async def _watch_device_plugged(self) -> None:
        """
        While the daemon drives the virtual device: whether the device of `[device] name` is plugged in, so the GUI can
        offer to switch to it (see `device_plugged`).
        """
        while True:
            plugged = isinstance(self.surface.port, SocketPort) and AlsaPort(self.config.device.name).present()
            if plugged != self.device_plugged:
                self.device_plugged = plugged
                if plugged:
                    _LOGGER.info(f"{self.config.device.name} is plugged in; the daemon drives the virtual device")
                self._changed()
            await asyncio.sleep(DEVICE_CHECK)

    async def _watch_file(self) -> None:
        """
        Loads the configuration file once it changed and rested (see FILE_CHECK), like a reload (SIGHUP): a file
        with errors is logged and the current configuration stays. A version that was loaded already (e.g. by the
        GUI, which reloads after it saved) is no change, and neither is a file that is gone: the daemon keeps what
        it runs.
        """
        seen = self._file_stamp
        while True:
            await asyncio.sleep(FILE_CHECK)
            stamp = self._stamp()
            if stamp is not None and stamp != self._file_stamp and stamp == seen:
                _LOGGER.info("The configuration file changed, loading it")
                self.reload()
            seen = stamp

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
        self._in_background(self.follow(), "slots")
        self._in_background(self._watch_twins(), "virtual twins")
        self._in_background(self._watch_file(), "configuration file")
        self._in_background(self._watch_device_plugged(), "the device while virtual")
        if self.live is not None:
            # not one of the parts: the daemon works without it. It stops last, after the shutdown sequence, which the
            # GUI shows too
            self._live_task = asyncio.create_task(self.live.run(), name="live view")
        if self.players is not None:
            self._in_background(self.players.run(), "media players")
        systemd.notify("READY=1", self._status())
        channels = len(self.config.slots.channels)
        _LOGGER.info(
            f"Running with {channels} channel{'s' if channels != 1 else ''}, waiting for {self.config.device.name}"
        )
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
        self._stopping = True
        self.end_test("the daemon stops")
        self.surface.on_event = lambda event: None
        for client in list(self._twins):
            # not news: the window loses its connection and asks the next daemon
            self._end_twin(client, None)
        self.close()
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
        await asyncio.gather(*self._closing, return_exceptions=True)
        await self.desk.wait_closed()
        await self.commands.wait_closed()

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.surface.put_away(), SHUTDOWN_TIMEOUT)

        # its end sends what is still queued and closes the device
        surface.cancel()
        await asyncio.gather(surface, return_exceptions=True)
        if self._live_task is not None:
            self._live_task.cancel()
            await asyncio.gather(self._live_task, return_exceptions=True)

    def _start_mixer(self) -> None:
        if self._mixer_task is not None:
            self._mixer_task.cancel()
        self._mixer_task = asyncio.create_task(self.mixer.run(), name="mixer")

    def _on_state(self, state: AudioState) -> None:
        was_connected = self.mixer.state.connected
        self.on_state(state)
        self._reality_changed()
        if self.devices_seen.see(state) and self.live is not None:
            self.live.publish_known()
        if state.connected != was_connected:
            systemd.notify(self._status())

    def _on_connection(self, connected: bool) -> None:
        if not connected:
            self.end_test("the device went away")
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

    def _changed(self) -> None:
        """Something the snapshot tells may have changed: the live view sends it (see `LiveServer.changed()`)."""
        if self.live is not None:
            self.live.changed()

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
            voip=voip_state(self.voip),
            slots=self.slots.view(),
            virtual=isinstance(self.surface.port, SocketPort),
            simulated=self.slots.situation is not None,
            test=self.testing,
            device_plugged=self.device_plugged,
        )

    def _status(self) -> str:
        device = self.config.device.name
        surface = f"{device} connected" if self.surface.connected else f"waiting for {device}"
        sound = "sound server connected" if self.mixer.state.connected else "waiting for the sound server"
        mqtt = ""
        if self.bridge is not None:
            mqtt = ", MQTT connected" if self.bridge.connected else ", waiting for MQTT"
        preview = ", previewing unsaved changes of the GUI" if self.previewing else ""
        test = ", testing the device" if self.testing else ""
        return f"STATUS={surface}, {sound}{mqtt}{preview}{test}"


def _refused(request: DaemonRequest) -> Reply | None:
    """The answer to a request of the live view while the daemon stops: no to what would start something."""
    why = "The daemon stops."
    match request:
        case StartPreview():
            return Reply("preview", False, why)
        case StartTest():
            return Reply("test", False, why)
        case SetMode():
            return Reply("mode", False, why)
        case SetOverride():
            return Reply("override", False, why)
        case _:
            return None
