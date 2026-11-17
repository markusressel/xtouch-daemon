"""
Helpers for the tests of channels, states and slots: configurations from TOML, states, what slots show.
"""

import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tests.support.audio import FakeBackend
from tests.support.daemon import QUIET
from tests.support.hardware import RecordingSurface
from tests.support.paths import DOCS
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.model import Config
from xtouch_daemon.runtime.binder import SlotMixer
from xtouch_daemon.runtime.daemon import voip_state
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.runtime.slots import SlotEngine
from xtouch_daemon.slots.inputs import Attendee
from xtouch_daemon.slots.model import DEFAULT, Scene
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.voip.demo import DemoProvider

EXAMPLE = DOCS / "design" / "channels-states-slots.toml"
"""The complete example of the design."""


def scene(text: str) -> Scene:
    return Scene.of(tomllib.loads(text))


def example() -> Scene:
    return Scene.of(tomllib.loads(EXAMPLE.read_text()))


def states(scene: Scene, *on: str, mode: str = DEFAULT) -> dict[str, bool]:
    """Every state off but `on`, and the mode."""
    values = {name: name in on for name in scene.states}
    values.update({name: name == mode for name in scene.modes})
    values[DEFAULT] = mode == DEFAULT
    return values


def attendees(*names: str) -> tuple[Attendee, ...]:
    """People in the voice chat, with ids that are not their names."""
    return tuple(Attendee(f"id-{name}", name) for name in names)


def shows(result: Result, slots: Iterable[int] = range(1, 9)) -> list[str]:
    return [str(result.slots[slot]) for slot in slots]


OLDER = Path(__file__).with_name("older_example.toml")
"""The example of the design before the live test: slot 2 dark while gaming, `call` waits 2 s."""


def older() -> Scene:
    return Scene.of(tomllib.loads(OLDER.read_text()))


class Rig:
    """A slot mixer on a recording surface, with the engine whose results it shows and the demo voice chat."""

    def __init__(self, surface: RecordingSurface, config: Config, **kwargs: Any) -> None:
        self.surface = surface
        assert config.voip is not None
        self.voip = DemoProvider(config.voip.participants)
        self.engine = SlotEngine(config)
        self.desk = Desk(surface, capture_command=QUIET)
        self.mixer = SlotMixer(surface, FakeBackend(()), config, self.engine, self.desk, self.voip, **kwargs)
        self.now = 0.0

    def step(self, state: AudioState, processes: frozenset[str] = frozenset(), flash: float = 0.0) -> None:
        """One step of the slots, a second after the one before; the slots under a finger are the desk's."""
        self.now += 1
        self.mixer.on_state(state)
        voip = voip_state(self.voip)
        self.mixer.apply(self.engine.step(state, processes, voip, self.desk.held_slots(), self.now), flash)

    def labels(self) -> list[str]:
        return [strip.text[0] for strip in self.surface.strips]
