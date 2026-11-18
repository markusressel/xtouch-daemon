"""
The base of the models of the configuration, its error, and the metadata of choices for the GUI.
"""

import difflib
import re
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import (
    BaseModel,
    ConfigDict,
)


class Model(BaseModel):
    # a typo in an option name is an error, not silently ignored; the docstrings of the fields are their descriptions,
    # which the GUI shows as help
    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)


@dataclass(frozen=True, eq=False)
class Meanings:
    """
    What the values of a choice mean, as metadata of its option (`Annotated[Indicator, INDICATORS]`): the GUI shows
    the meaning of the chosen value. Keep it in line with the tables of the docs.
    """

    meanings: Mapping[str, str]


class ConfigError(Exception):
    """A configuration that can't be used, with a message for the user."""


def known_options() -> frozenset[str]:
    """The names of the options of every model of the configuration (and their aliases): for hints on typos."""
    names: set[str] = set()
    pending = [Model]
    while pending:
        model = pending.pop()
        pending.extend(model.__subclasses__())
        for name, field in model.model_fields.items():
            names.add(name)
            if field.alias:
                names.add(field.alias)
    return frozenset(names)


_LABEL_REQUIRED = re.compile(r"(?:^|[ .])label: Field required$")


def hinted(line: str) -> str:
    """A line of the errors of a file with the hint a typo or a missing option calls for."""
    suffix = ": Extra inputs are not permitted"
    if line.endswith(suffix):
        name = line[: -len(suffix)].rsplit(" ", 1)[-1].rsplit(".", 1)[-1]
        close = difflib.get_close_matches(name, sorted(known_options()), n=1, cutoff=0.8)
        return f"{line} (did you mean {close[0]}?)" if close else line
    if _LABEL_REQUIRED.search(line):
        return f"{line} (the name of the strip on the LCD, up to 7 characters)"
    return line
