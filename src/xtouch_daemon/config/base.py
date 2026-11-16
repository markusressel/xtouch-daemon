"""
The base of the models of the configuration, its error, and the metadata of choices for the GUI.
"""

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
