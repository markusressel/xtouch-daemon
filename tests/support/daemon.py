"""
Helpers for the tests of the daemon: its configuration file, and starting it with fakes.
"""

import asyncio
from pathlib import Path

from tests.support.audio import FakeBackend, output
from tests.support.hardware import RecordingSurface
from tests.support.mqtt import FakeBroker
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime.daemon import Daemon

SPEAKER = '[[strip]]\ntype = "output"\ndevice = "speaker"\nlabel = "Speaker"\ncolor = "cyan"\n'


STATE = AudioState(outputs=(output("speaker", 50),), default_output="speaker")


class Notifications(list[tuple[str, ...]]):
    def states(self) -> list[str]:
        return [state for notification in self for state in notification]


QUIET = "true"
"""A capture command for meters that capture nothing: the tests don't touch the audio of the machine they run on."""


def make(config_path: Path, surface: RecordingSurface, backend: FakeBackend) -> Daemon:
    return Daemon(parse_config(config_path.read_text()), backend, surface, config_path, capture_command=QUIET)


async def until(condition: object) -> None:
    for _ in range(100):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the condition never became true")


HOME_ASSISTANT = '[[strip]]\ntype = "homeassistant"\nlabel = "Lights"\n\n[mqtt]\nhost = "broker"\n'


def make_with_mqtt(config_path: Path, surface: RecordingSurface, backend: FakeBackend, broker: FakeBroker) -> Daemon:
    config = parse_config(config_path.read_text())
    assert config.mqtt is not None
    bridge = MqttBridge(config.mqtt, client_factory=broker.client)
    return Daemon(config, backend, surface, config_path, capture_command=QUIET, bridge=bridge)
