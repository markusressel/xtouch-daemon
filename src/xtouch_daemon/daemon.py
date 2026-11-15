"""
The daemon: the surface, the sound server connection and the mixer of the current configuration, for as long as it
runs. SIGHUP (`systemctl --user reload xtouch-daemon`) loads the configuration again, SIGTERM/SIGINT stop it, and
it leaves the surface dark, so it is clear that nothing drives it anymore.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon import systemd
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import Config, ConfigError, load_config
from xtouch_daemon.mixer import Mixer
from xtouch_daemon.surface import Surface

_LOGGER = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 2.0
"""How long the faders may take to move down when the daemon stops."""


class Daemon:
    def __init__(
        self,
        config: Config,
        backend: AudioBackend,
        surface: Surface | None = None,
        config_path: Path | None = None,
        mixer_factory: Callable[[Surface, AudioBackend, Config], Mixer] = Mixer,
    ):
        self.config = config
        self.config_path = config_path
        self.backend = backend
        self.surface = surface or Surface(config.device.name)
        self._mixer_factory = mixer_factory
        self.mixer = mixer_factory(self.surface, backend, config)
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
        if config.device != self.config.device:
            _LOGGER.warning("The [device] section changed: restart the daemon for it to take effect")
        self.mixer.close()
        self.config = config
        self.mixer = self._mixer_factory(self.surface, self.backend, config)
        self.mixer.on_state(self._state())
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
        tasks = [
            asyncio.create_task(self.surface.run(), name="surface"),
            asyncio.create_task(self.backend.run(self._on_state), name="sound server"),
        ]
        self._start_mixer()
        systemd.notify("READY=1", self._status())
        _LOGGER.info(f"Running with {len(self.mixer.controllers)} strips, waiting for {self.config.device.name}")
        try:
            stopped = asyncio.create_task(self._stop.wait())
            done, _ = await asyncio.wait([stopped, *tasks], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopped:
                    # a part of the daemon ended, which they never do on their own
                    task.result()
        finally:
            systemd.notify("STOPPING=1")
            for signum in handlers:
                loop.remove_signal_handler(signum)
            await self._shutdown(tasks)

    async def _shutdown(self, tasks: list[asyncio.Task[None]]) -> None:
        _LOGGER.info("Stopping")
        self.mixer.close()
        if self._mixer_task is not None:
            self._mixer_task.cancel()
        for strip in self.surface.strips:
            strip.reset()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.surface.settled(), SHUTDOWN_TIMEOUT)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, *([self._mixer_task] if self._mixer_task else []), return_exceptions=True)

    def _start_mixer(self) -> None:
        if self._mixer_task is not None:
            self._mixer_task.cancel()
        self._mixer_task = asyncio.create_task(self.mixer.run(), name="mixer")

    def _state(self) -> AudioState:
        return self.mixer.state

    def _on_state(self, state: AudioState) -> None:
        was_connected = self.mixer.state.connected
        self.mixer.on_state(state)
        if state.connected != was_connected:
            systemd.notify(self._status())

    def _on_connection(self, connected: bool) -> None:
        # the surface shows everything again by itself after a connect
        systemd.notify(self._status())

    def _status(self) -> str:
        device = self.config.device.name
        surface = f"{device} connected" if self.surface.connected else f"waiting for {device}"
        sound = "sound server connected" if self.mixer.state.connected else "waiting for the sound server"
        return f"STATUS={surface}, {sound}"
