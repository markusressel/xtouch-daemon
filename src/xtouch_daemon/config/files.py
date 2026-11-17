"""
Reading the configuration file, and its errors for people.
"""

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from pydantic import (
    ValidationError,
)

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.legacy.strips import LEGACY_STRIP_TYPES
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.slots import setup, split

APP_NAME = "xtouch-daemon"

REPLACED = {
    ("behavior", "auto_hold"): "hold of [pool.auto]",
    ("behavior", "ignore"): "exclude of [pool.auto]",
    ("behavior", "collapse_hold"): "absent_after of a channel",
    ("switching", "hold"): "delay_off of each mode",
}
"""Options of strips and layouts, and what channels, states and slots have instead."""


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME / "config.toml"


def example_config() -> str:
    """The example configuration (`init-config`, the GUI's new file, and the defaults without a file)."""
    return resources.files("xtouch_daemon").joinpath("config.example.toml").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Problem:
    """One error of a configuration: where it is, and what is wrong."""

    path: tuple[int | str, ...]
    """Where in the TOML data, e.g. `("strip", 2, "label")` for the label of the third strip."""
    message: str
    kind: str
    """The kind of error (pydantic's error type), e.g. `extra_forbidden` for an unknown option."""

    @property
    def location(self) -> str:
        """The path for people, e.g. `strip[3].label`."""
        parts: list[str] = []
        for part in self.path:
            if isinstance(part, int) and parts:
                parts[-1] = f"{parts[-1]}[{part + 1}]"
            else:
                parts.append(str(part))
        return ".".join(parts)

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


def problems_of(error: ValidationError) -> list[Problem]:
    problems: list[Problem] = []
    for item in error.errors():
        loc = item["loc"]
        # the type of a strip follows its position in the path of its errors (`strip.2.apps.label`), but is not part
        # of the TOML data
        path = tuple(
            part for i, part in enumerate(loc) if not (i and isinstance(loc[i - 1], int) and part in LEGACY_STRIP_TYPES)
        )
        # pydantic puts "Value error, " before the messages of the validators here
        problems.append(Problem(path, item["msg"].removeprefix("Value error, "), item["type"]))
    return problems


def parse_config(text: str, source: str = "config") -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{source} is not valid TOML: {e}") from e
    if "strip" in data or "layout" in data:
        raise ConfigError(
            f"{source} has strips and layouts, which are gone: `xtouch-daemon migrate-config` writes it as channels, "
            "states and slots"
        )
    replaced = [
        f"  {section}.{option}: gone with strips and layouts, see {instead}"
        for (section, option), instead in REPLACED.items()
        if option in data.get(section, {})
    ]
    if replaced:
        raise ConfigError(f"{source} has errors:\n" + "\n".join(replaced))
    rest, slots = split(data)
    try:
        config = Config.model_validate(rest)
    except ValidationError as e:
        problems = "\n".join(f"  {problem}" for problem in problems_of(e))
        raise ConfigError(f"{source} has errors:\n{problems}") from e
    try:
        return setup(config, slots or {})
    except ConfigError as e:
        problems = "\n".join(f"  {line}" for line in str(e).splitlines())
        raise ConfigError(f"{source} has errors:\n{problems}") from e


def load_config(path: Path | None = None) -> Config:
    """
    The configuration from the file. Without a file at the default path it is the example configuration (6 `auto`
    slots, the default input and the default output), so the daemon is useful right away.
    """
    explicit = path is not None
    path = path or default_config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if explicit:
            raise ConfigError(f"{path} does not exist") from None
        return parse_config(example_config(), "the example configuration")
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e}") from e
    return parse_config(text, str(path))
