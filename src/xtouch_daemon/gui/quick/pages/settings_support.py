"""
What the page Settings does in threads: trying the broker, and building and installing the plugin of a voice chat
client. Each ends with a result whatever happens, so the page never waits for good.
"""

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from xtouch_daemon.config.sections import MqttConfig
from xtouch_daemon.gui.domain.broker import try_broker
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.voip import CLIENTS, ClientSetup, PluginSetup
from xtouch_daemon.voip import mumble, teamspeak

log = logging.getLogger(__name__)

type BrokerTest = Callable[[MqttConfig], Awaitable[Status]]


class BrokerTester(QObject):
    """Tries settings of the [mqtt] section in a thread, so a broker that does not answer does not block the window."""

    finished = pyqtSignal(object, arguments=["status"])
    """The result of the latest test; one that a newer test overtook is dropped."""
    _done = pyqtSignal(int, object, arguments=["number", "status"])

    def __init__(self, test: BrokerTest = try_broker):
        super().__init__()
        self._test = test
        self.started = 0
        """How many tests started: the number of the latest one."""
        # in the thread of the window, after the thread of the test
        self._done.connect(self._deliver)

    def start(self, config: MqttConfig) -> None:
        self.started += 1
        threading.Thread(target=self._run, args=(config, self.started), name="broker test", daemon=True).start()

    def _run(self, config: MqttConfig, number: int) -> None:
        try:
            status = asyncio.run(self._test(config))
        except Exception as e:
            # the test ends with a result, whatever happens: the button would stay at "Connecting to ..."
            log.exception("Trying the broker failed")
            status = Status(f"Can't connect: {type(e).__name__}: {e}.", Tone.BAD)
        self._done.emit(number, status)

    def _deliver(self, number: int, status: Status) -> None:
        if number == self.started:
            self.finished.emit(status)


class PluginInstaller(QObject):
    """
    Builds the plugin of a voice chat client if needed and copies it into the client (`ClientSetup.install`) in a
    thread: a build takes a few seconds. `finished` tells what happens next, or what went wrong.
    """

    finished = pyqtSignal(object, arguments=["status"])

    def __init__(
        self,
        client: ClientSetup,
        install: Callable[[], str] | None = None,
        setup: Callable[[], PluginSetup] | None = None,
    ):
        super().__init__()
        self.client = client
        self._install = install or client.install
        self.setup = setup or client.setup

    def start(self) -> None:
        threading.Thread(target=self._run, name=f"{self.client.key} plugin", daemon=True).start()

    def _run(self) -> None:
        try:
            status = Status(self._install(), Tone.GOOD)
        except (mumble.MumbleError, teamspeak.TeamSpeakError) as e:
            status = Status(str(e), Tone.BAD)
        except Exception as e:
            # the install ends with a result, whatever happens: the button would wait for it for good
            log.exception("Setting up the plugin of %s failed", self.client.key)
            status = Status(f"The setup failed: {type(e).__name__}: {e}.", Tone.BAD)
        self.finished.emit(status)


def default_installers() -> list[PluginInstaller]:
    return [PluginInstaller(client) for client in CLIENTS]
