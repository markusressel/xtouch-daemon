"""
Helpers for the tests of channels, states and slots: configurations from TOML, states, what slots show.
"""

import tomllib
from collections.abc import Iterable
from pathlib import Path

from tests.support.paths import DOCS
from xtouch_daemon.slots.inputs import Attendee
from xtouch_daemon.slots.model import DEFAULT, Scene
from xtouch_daemon.slots.resolver import Result

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
