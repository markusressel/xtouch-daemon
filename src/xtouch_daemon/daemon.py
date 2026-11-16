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
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Protocol, assert_never

from xtouch_daemon import __version__, protocol, systemd
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import Config, ConfigError, default_config_path, load_config, parse_config
from xtouch_daemon.live import (
    FEATURES,
    EndPreview,
    KeepPreview,
    LiveServer,
    MqttState,
    Reply,
    Request,
    Snapshot,
    StartPreview,
    fingerprint,
    strip_states,
)
from xtouch_daemon.media import MediaPlayers
from xtouch_daemon.mixer import Mixer
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.surface import Surface

_LOGGER = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 4.0
"""How long the faders may take to move down when the daemon stops (they go slowly, see FADER_SLOW_SMOOTH_TIME)."""
PREVIEW_TIMEOUT = 10.0
"""How long a preview runs without a request of its GUI (`live.KeepPreview`) before the daemon goes back to the file."""
PREVIEW_CHECK = 1.0
"""How often a running preview checks for its GUI and whether the configuration file changed."""


class MixerFactory(Protocol):
    def __call__(
        self,
        surface: Surface,
        backend: AudioBackend,
        config: Config,
        *,
        bridge: MqttBridge | None,
        players: MediaPlayers | None,
        preview: bool = False,
    ) -> Mixer: ...


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
        mixer_factory: MixerFactory = Mixer,
        bridge: MqttBridge | None = None,
        live_socket: Path | None = None,
        players: MediaPlayers | None = None,
    ):
        """
        `bridge` is by default the one of the [mqtt] section, if there is one. `live_socket` is where the live view
        for the GUI is served (see `live.py`), None for none. `players` are the media players of the session, for
        `encoder = "media"`.
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
        """When the previewer sent its last request (`time.monotonic()`)."""
        self._watchdog: asyncio.Task[None] | None = None
        self._file_stamp = self._stamp()
        self.backend = backend
        self.surface = surface or Surface(config.device.name)
        self._configure_surface(config)
        self.bridge = bridge or (MqttBridge(config.mqtt) if config.mqtt is not None else None)
        if self.bridge is not None:
            self.bridge.on_connection = self._on_mqtt_connection
        self._mixer_factory = mixer_factory
        self.mixer = mixer_factory(self.surface, backend, config, bridge=self.bridge, players=players)
        self._background: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()
        self._mixer_task: asyncio.Task[None] | None = None
        self.surface.on_event = lambda event: self.mixer.on_event(event)
        self.surface.on_connection = self._on_connection
        self.live = (
            LiveServer(live_socket, self.snapshot, self.on_request, self.on_client_closed)
            if live_socket is not None
            else None
        )

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

    def _use(self, config: Config, preview: bool = False) -> None:
        """A new mixer for `config` on the same surface, sound server and broker."""
        self._configure_surface(config)
        state = self.mixer.state
        self.mixer.close()
        self.config = config
        self.mixer = self._mixer_factory(
            self.surface, self.backend, config, bridge=self.bridge, players=self.players, preview=preview
        )
        # the sound server reports again only once something changes
        self.mixer.on_state(state)
        self._start_mixer()

    def _stamp(self) -> tuple[int, int] | None:
        """When the configuration file changed last, and its size; None without a file."""
        try:
            stat = (self.config_path or default_config_path()).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    # -- the live preview of the GUI ------------------------------------------------------------------------------

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
                    self._preview_seen = time.monotonic()
                return None
            case EndPreview():
                if client is self._previewer:
                    self._back_to_file("the GUI ended it")
                return None
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
        self._preview_seen = time.monotonic()
        if previous is None:
            _LOGGER.info("Previewing a configuration of the GUI, the file stays as it is")
            self._watchdog = asyncio.create_task(self._watch_preview(), name="preview watch")
        changed = fingerprint(config) != fingerprint(self.config)
        if previous is None or changed:
            _LOGGER.debug("Running the previewed configuration")
            self._use(config, preview=True)
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
            if time.monotonic() - self._preview_seen > PREVIEW_TIMEOUT:
                self._back_to_file(f"no word from the GUI for {PREVIEW_TIMEOUT:.0f} s")
                return

    # -- running --------------------------------------------------------------------------------------------------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        handlers = {signal.SIGTERM: self.stop, signal.SIGINT: self.stop, signal.SIGHUP: self.reload}
        for signum, handler in handlers.items():
            loop.add_signal_handler(signum, handler)
        surface = asyncio.create_task(self.surface.run(), name="surface")
        parts = [asyncio.create_task(self.backend.run(self._on_state), name="sound server")]
        if self.bridge is not None:
            parts.append(asyncio.create_task(self.bridge.run(), name="mqtt"))
        self._start_mixer()
        if self.live is not None:
            # not one of the parts: the daemon works without it
            self._in_background(self.live.run(), "live view")
        if self.players is not None:
            self._in_background(self.players.run(), "media players")
        systemd.notify("READY=1", self._status())
        _LOGGER.info(f"Running with {len(self.mixer.controllers)} strips, waiting for {self.config.device.name}")
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
        if self.bridge is not None:
            # while it is still connected: Home Assistant sees the entities unavailable right away
            await self.bridge.close()
        assert self._mixer_task is not None, "run() starts the mixer"
        others = [*parts, self._mixer_task, *self._background]
        if self._watchdog is not None:
            others.append(self._watchdog)
        for task in others:
            task.cancel()
        await asyncio.gather(*others, return_exceptions=True)

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
        if state.connected != was_connected:
            systemd.notify(self._status())

    def _on_connection(self, connected: bool) -> None:
        # the surface shows everything again by itself after a connect
        systemd.notify(self._status())
        if self.bridge is not None:
            # Home Assistant greys out the entities of a device that is not there
            self._in_background(self.bridge.set_available(connected), "mqtt availability")

    def _on_mqtt_connection(self, connected: bool) -> None:
        self.mixer.refresh()
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
