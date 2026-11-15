"""
The options of the configuration as the editor sees them, read from the pydantic models: their kind of value, choices,
bounds, defaults and help. Forms built from these show a new option without changes to the GUI.
"""

import types
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import annotated_types
from pydantic import BaseModel, SecretStr
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from xtouch_daemon.config import STRIP_MODELS, ColorName, Config


class Kind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    NUMBER = "number"
    SWITCH = "switch"
    CHOICE = "choice"
    COLOR = "color"
    LIST = "list"
    """A list of texts."""
    SECRET = "secret"
    """A text that is not shown, e.g. a password."""
    PATH = "path"
    """The path of a file."""
    TABLES = "tables"
    """A list of tables with texts (`Option.columns`), e.g. the profiles of a strip."""


@dataclass(frozen=True)
class Option:
    """One option of a section or a strip."""

    name: str
    kind: Kind
    help: str
    default: Any
    """The value without the option, None for a required option or one that is unset by default."""
    required: bool
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    max_length: int | None = None
    """The most characters of a text."""
    columns: tuple[Option, ...] = ()
    """The options of each table of `TABLES`."""

    @property
    def title(self) -> str:
        """The name for people, e.g. "Max volume" for `max_volume`."""
        return self.name.replace("_", " ").capitalize()


def _unwrap(annotation: Any) -> tuple[Any, list[Any]]:
    """The type of an annotation without `None` and `Annotated`, and the constraints that came with them."""
    constraints: list[Any] = []
    if get_origin(annotation) in (Union, types.UnionType):
        (annotation,) = (arg for arg in get_args(annotation) if arg is not type(None))
    while get_origin(annotation) is Annotated:
        annotation, *metadata = get_args(annotation)
        for item in metadata:
            constraints.extend(item.metadata if isinstance(item, FieldInfo) else [item])
    return annotation, constraints


def _table_model(annotation: Any) -> type[BaseModel] | None:
    """The model of the tables of `tuple[SomeModel, ...]`."""
    if get_origin(annotation) is tuple:
        item = get_args(annotation)[0]
        if isinstance(item, type) and issubclass(item, BaseModel):
            return item
    return None


def _kind(annotation: Any) -> Kind:
    if _table_model(annotation) is not None:
        return Kind.TABLES
    if annotation == ColorName:
        return Kind.COLOR
    if get_origin(annotation) is Literal:
        return Kind.CHOICE
    if annotation == tuple[str, ...]:
        return Kind.LIST
    kinds = {
        bool: Kind.SWITCH,
        int: Kind.INTEGER,
        float: Kind.NUMBER,
        str: Kind.TEXT,
        SecretStr: Kind.SECRET,
        Path: Kind.PATH,
    }
    if annotation not in kinds:
        raise TypeError(f"the editor has no form field for options of type {annotation}")
    return kinds[annotation]


def option(name: str, field: FieldInfo) -> Option:
    annotation, constraints = _unwrap(field.annotation)
    constraints += field.metadata
    kind = _kind(annotation)
    bounds: dict[str, Any] = {}
    for constraint in constraints:
        match constraint:
            case annotated_types.Ge(ge=value):
                bounds["minimum"] = value
            case annotated_types.Le(le=value):
                bounds["maximum"] = value
            case annotated_types.MaxLen(max_length=value) if kind == Kind.TEXT:
                bounds["max_length"] = value
            case _:
                # the remaining ones are checked by validation only, e.g. the pattern of a label
                pass
    return Option(
        name=name,
        kind=kind,
        help=field.description or "",
        default=None if field.default is PydanticUndefined else field.default,
        required=field.is_required(),
        choices=get_args(annotation) if kind in (Kind.CHOICE, Kind.COLOR) else (),
        columns=options(table) if (table := _table_model(annotation)) is not None else (),
        **bounds,
    )


def options(model: type[BaseModel], skip: tuple[str, ...] = ()) -> tuple[Option, ...]:
    """The options of a model in the order it declares them."""
    return tuple(option(name, field) for name, field in model.model_fields.items() if name not in skip)


@dataclass(frozen=True)
class Section:
    """A section of the configuration with options of its own, like `[behavior]`."""

    name: str
    model: type[BaseModel]
    optional: bool
    """Whether the section may be missing (`[mqtt]`), rather than having defaults for all its options."""
    help: str


def sections() -> tuple[Section, ...]:
    """The sections of the configuration with options of their own, in the order `Config` declares them."""
    result: list[Section] = []
    for name, field in Config.model_fields.items():
        annotation, _ = _unwrap(field.annotation)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            optional = type(None) in get_args(field.annotation)
            help_text = " ".join((annotation.__doc__ or "").split())
            result.append(Section(name, annotation, optional, help_text))
    return tuple(result)


def strip_models() -> dict[str, type[BaseModel]]:
    """The model of every strip type, by the value of `type`."""
    return {name: model for model in STRIP_MODELS for name in get_args(model.model_fields["type"].annotation)}


def strip_options(strip_type: str) -> tuple[Option, ...]:
    """The options of a strip of the type, without `type` itself."""
    return options(strip_models()[strip_type], skip=("type",))
