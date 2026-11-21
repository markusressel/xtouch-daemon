"""
What the slots keep across restarts, in the state directory of the daemon (`instance.state_dir()`): the overrides and
the mode picked (`slots.json`), and the order of the people (`people.json`). Errors are logged, never raised: the
daemon runs on without them.
"""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

from xtouch_daemon.slots.model import DEFAULT, Scene
from xtouch_daemon.slots.simulation import Known
from xtouch_daemon.slots.states import Override

_LOGGER = logging.getLogger(__name__)

PEOPLE_FILE_NAME = "people.json"
"""The file of the order of the people, in the state directory of the daemon."""
CHOICES_FILE_NAME = "slots.json"
"""The file of the overrides and the mode picked, in the state directory of the daemon."""

type Choices = tuple[Mapping[str, Override], str | None]
"""What was chosen by hand: the overrides of states, and the mode picked (None for the rules)."""


def read_people(path: Path, now: float, wall_now: float) -> dict[str, float]:
    """The people `write_people()` kept, at times of the clock that says `now` (none without a readable file)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        _LOGGER.warning(f"Can't read the order of the people from {path}: {e}")
        return {}
    return {str(person): now - (wall_now - float(at)) for person, at in data}


def write_people(path: Path, known: Known, now: float, wall_now: float) -> None:
    """Keeps the people known for the next start, in their order, with wall-clock times. Errors are logged."""
    data = [[person, round(wall_now - (now - at), 1)] for person, at in known.items()]
    _write(path, data, "the order of the people")


def _write(path: Path, data: object, what: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # whole or not at all
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as e:
        _LOGGER.warning(f"Can't keep {what} in {path}: {e}")


def read_choices(path: Path, scene: Scene) -> Choices:
    """The choices `write_choices()` kept, those that still fit the scene (none without a readable file)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        overrides = {str(name): Override(value) for name, value in data["overrides"].items()}
        mode = data["mode"]
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        _LOGGER.warning(f"Can't read the overrides and the mode from {path}: {e}")
        return {}, None
    kept = {name: value for name, value in overrides.items() if name in scene.states and not scene.states[name].mode}
    return kept, mode if mode == DEFAULT or mode in scene.modes else None


def write_choices(path: Path, choices: Choices) -> None:
    """Keeps the choices for the next start. Errors are logged."""
    overrides, mode = choices
    _write(
        path,
        {"overrides": {name: value.value for name, value in overrides.items()}, "mode": mode},
        "the overrides and the mode",
    )
