"""
The daemon: the surface, the sound server connection and the mixer of the current configuration, for as long as it
runs. SIGHUP (`systemctl --user reload xtouch-daemon`) loads the configuration again, SIGTERM/SIGINT stop it, and
it leaves the surface dark, so it is clear that nothing drives it anymore.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Protocol

from xtouch_daemon import systemd
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import Config, ConfigError, load_config
from xtouch_daemon.mixer import Mixer
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.surface import Surface

_LOGGER = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 2.0
"""How long the faders may take to move down when the daemon stops."""


class MixerFactory(Protocol):
    def __call__(
        self, surface: Surface, backend: AudioBackend, config: Config, *, bridge: MqttBridge | None
    ) -> Mixer: ...


class Daemon:
    def __init__(
        self,
        config: Config,
        backend: AudioBackend,
        surface: Surface | None = None,
        config_path: Path | None = None,
        mixer_factory: MixerFactory = Mixer,
        bridge: MqttBridge | None = None,
    ):
        """`bridge` is by default the one of the [mqtt] section, if there is one."""
        self.config = config
        self.config_path = config_path
        self.backend = backend
        self.surface = surface or Surface(config.device.name)
        self.bridge = bridge or (MqttBridge(config.mqtt) if config.mqtt is not None else None)
        if self.bridge is not None:
            self.bridge.on_connection = self._on_mqtt_connection
        self._mixer_factory = mixer_factory
        self.mixer = mixer_factory(self.surface, backend, config, bridge=self.bridge)
        self._background: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()
        self._mixer_task: asyncio.Task[None] | None = None
        self.surface.on_event = lambda event: self.mixer.on_event(event)
        self.surface.on_connection = self._on_connection

    # -- control --------------------------------------------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    def reload(self) -> bool:
        """Loads the configuration again. A configuration with errors is reported and the current one kept."""
        systemd.reloading()
        try:
            config = load_config(self.config_path)
        except ConfigError as e:
            _LOGGER.error(f"Keeping the current configuration: {e}")
            systemd.notify("READY=1", "STATUS=Configuration has errors, see the log")
            return False
        if config.mqtt != self.config.mqtt:
            # the connection and the entities of the strips depend on it
            _LOGGER.error("Keeping the current configuration: the [mqtt] section changed, restart the daemon instead")
            systemd.notify("READY=1", "STATUS=The [mqtt] section changed, restart the daemon")
            return False
        if config.device != self.config.device:
            _LOGGER.warning("The [device] section changed: restart the daemon for it to take effect")
        state = self.mixer.state
        self.mixer.close()
        self.config = config
        self.mixer = self._mixer_factory(self.surface, self.backend, config, bridge=self.bridge)
        # the sound server reports again only once something changes
        self.mixer.on_state(state)
        self._start_mixer()
        _LOGGER.info("Configuration loaded again")
        systemd.notify("READY=1", self._status())
        return True

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
            for signum in handlers:
                loop.remove_signal_handler(signum)
            stopped.cancel()
            await self._shutdown(surface, parts)

    async def _shutdown(self, surface: asyncio.Task[None], parts: list[asyncio.Task[None]]) -> None:
        """
        Leaves the surface dark: first everything stops that could show something on it (the sound server, Home
        Assistant, the mixer, the device's own events), then the strips are reset, and only then the surface closes.
        """
        _LOGGER.info("Stopping")
        self.surface.on_event = lambda event: None
        self.mixer.close()
        if self.bridge is not None:
            # while it is still connected: Home Assistant sees the entities unavailable right away
            await self.bridge.close()
        assert self._mixer_task is not None, "run() starts the mixer"
        others = [*parts, self._mixer_task, *self._background]
        for task in others:
            task.cancel()
        await asyncio.gather(*others, return_exceptions=True)

        for strip in self.surface.strips:
            strip.reset()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.surface.settled(), SHUTDOWN_TIMEOUT)

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

    def _status(self) -> str:
        device = self.config.device.name
        surface = f"{device} connected" if self.surface.connected else f"waiting for {device}"
        sound = "sound server connected" if self.mixer.state.connected else "waiting for the sound server"
        mqtt = ""
        if self.bridge is not None:
            mqtt = ", MQTT connected" if self.bridge.connected else ", waiting for MQTT"
        return f"STATUS={surface}, {sound}{mqtt}"
