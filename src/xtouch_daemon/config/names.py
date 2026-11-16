"""
Lists of names of applications and processes, which may hold presets (`@browsers`): they keep the entries
as written next to what the presets stand for.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from pydantic import AfterValidator, ModelWrapValidatorHandler, PrivateAttr, model_validator

from xtouch_daemon.config import presets
from xtouch_daemon.config.base import Model


def _no_blank(value: tuple[str, ...]) -> tuple[str, ...]:
    if any(not pattern.strip() for pattern in value):
        raise ValueError("an empty pattern would match every application")
    return value


@dataclass(frozen=True)
class Presets:
    """
    The metadata of a list of names that may have presets (`@browsers`): what its names are matched against. The
    list holds the expanded names; `WithPresets.written()` has the entries as written.
    """

    kind: presets.Kind


def _expand_streams(value: tuple[str, ...]) -> tuple[str, ...]:
    return presets.expand(value, presets.Kind.STREAMS)


def _expand_processes(value: tuple[str, ...]) -> tuple[str, ...]:
    return presets.expand(value, presets.Kind.PROCESSES)


StreamNames = Annotated[
    tuple[str, ...], AfterValidator(_no_blank), AfterValidator(_expand_streams), Presets(presets.Kind.STREAMS)
]
"""Parts of the names or binaries of applications (ignoring case), and presets of them."""
ProcessNames = Annotated[
    tuple[str, ...], AfterValidator(_no_blank), AfterValidator(_expand_processes), Presets(presets.Kind.PROCESSES)
]
"""Parts of the names of processes (ignoring case), and presets of them."""


class WithPresets(Model):
    """A model with lists of names (`StreamNames`, `ProcessNames`): they keep the entries as written."""

    _written: dict[str, tuple[str, ...]] = PrivateAttr(default_factory=dict)
    """The lists with presets as written, by option; the options hold what the presets stand for."""

    @model_validator(mode="wrap")
    @classmethod
    def _keep_written(cls, data: object, handler: ModelWrapValidatorHandler[WithPresets]) -> WithPresets:
        model = handler(data)
        if isinstance(data, Mapping):
            for name in cls.preset_options():
                written = data.get(name)
                if isinstance(written, list | tuple) and any(presets.is_preset(str(entry)) for entry in written):
                    model._written[name] = tuple(map(str, written))
        return model

    @classmethod
    def preset_options(cls) -> dict[str, presets.Kind]:
        """The options that are lists of names with presets, and what their names are matched against."""
        return {
            name: item.kind
            for name, field in cls.model_fields.items()
            for item in field.metadata
            if isinstance(item, Presets)
        }

    def written(self, name: str) -> tuple[str, ...]:
        """The entries of a list of names as written, with the presets (e.g. `@browsers`) instead of their names."""
        written: tuple[str, ...] = self._written[name] if name in self._written else getattr(self, name)
        return written
